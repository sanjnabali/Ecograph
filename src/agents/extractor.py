"""
agents/extractor.py - Scope3Extractor: LLM-powered triple extraction.

Reads parsed JSON files from data/parsed_content/,
calls Gemini via Langchain with rate-limiting + retry logic,
and writes *_triples.json files to data/triples/. 
"""

import json
import os
import logging
import time
from pathlib import Path
from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from src.agents.schema import ExtractionResult, Triple
from src.config.settings import(
    MAX_RETRIES,
    MIN_CHUNK_LENGTH,
    PARSED_CONTENT_DIR,
    RATE_LIMIT_DELAY,
    RETRY_BACKOFF,
    TRIPLES_DIR,
)

logger = logging.getLogger(__name__)





_SYSTEM_PROMPT = """\
You are an expert ESG analyst and knowledge graph engineer.

Your job is to extract structured triples from corporate sustainability reports.
Each triple must follow the format:
    subject   -> a named entity (Company, Facility, Scope Label)
    predicate -> an UPPER_SNAKE_CASE relationship
    object    -> a target entity, numeric value, or year

CRITICAL RULES FOR EXTRACTION:
1. UNIFY SUBJECTS: Never use "The company", "The Company", "Incorporated", "we", or "our staff". You MUST resolve these to the exact, primary brand name (e.g., "The Cheesecake Factory").
2. CONTEXTUALIZE METRICS: When using REPORTS_METRIC, the object_value MUST include the number AND the descriptive context (e.g., "3,371 new restaurants", not just "3,371").
3. NO NOISE & NO EMPTY FILES: Ignore nutritional labels, website URLs, and phone numbers. If a report is sparse, extract at least the basic operational facts. Never return an empty list.

Use standard predicates like: HAS_INITIATIVE, REPORTS_METRIC, REPORTS_EMISSION, HAS_SUPPLIER, USES_STANDARD, COMMITTED_TO.
"""
_HUMAN_PROMPT = "Extract all relevant triples from the following text:\n\n{text}"



#Extractor 


class Scope3Extractor:
    """
    Wraps a Gemini LLM chain with:
    - Pydantic structured output enforcement
    - Per-call rate limiting (free-tier safe)
    - Exponential backoff on quota errors
    - Per-document resumability (skips already-processed files)
    """

    def __init__(
        self
) -> None:
        self._validate_api_key()
        
        llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            temperature=0.0,
        )
        structured_llm = llm.with_structured_output(ExtractionResult)

        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            ("human", _HUMAN_PROMPT),
        ])

        self._chain = prompt | structured_llm
        logger.info(f"Scope3Extractor ready model={os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')}")



        #Public api


    def process_all_documents(self, input_dir: Path = PARSED_CONTENT_DIR,
                               output_dir: Path = TRIPLES_DIR) -> List[Path]:
        """
        Processes every .json file in `input_dir`.
        Returns the list of triple file paths that were written.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        if not input_dir.exists():
            logger.error(
                f"Input directory not found: {input_dir}."
                f" Ensure parsing step completed successfully."
            )
            return []
        
        json_files = sorted(input_dir.glob("*.json"))
        if not json_files:
            logger.warning(f"No JSON files found in {input_dir}. Nothing to process.")
            return []
        
        logger.info(
            f"Found {len(json_files)} parsed file(S)."
            f"Rate-limit: {RATE_LIMIT_DELAY}s/call"
            f"(~{int(60 / RATE_LIMIT_DELAY)} RPM - within Groq free-tier)."
        )


        written: List[Path] = []
        for file_path in json_files:
            out = self.process_document(file_path, output_dir)
            if out:
                written.append(out)

        logger.info(f"Batch Extraction complete. {len(written)} file(s) written.")
        return written
    

    def process_document(self, input_path: Path, output_dir: Path) -> Optional[Path]:
        """
        Extracts triples from a single parsed JSon file.
        Returns the output Path, or None if the files was skipped / failed.
        Skips the file if a triples output already exists (crash-safe resumability).
        """
        output_file = output_dir / f"{input_path.stem}_triples.json"

        if output_file.exists():
            logger.info(f"Skipping {input_path.name} - output already exists.")
            return output_file
        
        logger.info(f"{'-'*50}")
        logger.info(f"Processing {input_path.name}...  ")

        elements = self._load_json(input_path)
        if elements is None:
            return None
        
        chunks = self._filter_chunks(elements, input_path.name)
        triples = self._extract_all_chunks(chunks)

        self.save(triples, output_file, input_path.name)
        return output_file
    
    #internals

    @staticmethod
    def _validate_api_key():
        if not os.getenv("GROQ_API_KEY"):
            raise ValueError(
                "GROQ_API_KEY environment variable not set. "
                "Please set it to your GROQ API key before running."
            )
        
    @staticmethod
    def _load_json(path: Path) -> Optional[List[dict]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to load {path.name}: {e}")
            return None
        except OSError as e:
            logger.error(f"cannot open {path.name}: {e}")
        return None
    
    @staticmethod
    def _filter_chunks(elements: List, filename: str) -> List[str]:
        """
        Keeps only meaningful compositeelement / table chunks.
        """
        chunks  = [
            el.get("text", "")
            for el in elements
            if el.get("type") in ("CompositeElement", "Table") and len(el.get("text", "")) >= MIN_CHUNK_LENGTH
        ]
        if not chunks:
            logger.warning(f"No meaningful chunks in {filename}"
                           "Verify that parsing produced CompositeElement or Table types with sufficient text.")
            
        return chunks
    
    def _extract_all_chunks(self, chunks: List[str]) -> List[dict]:
        """
        Calls the LLM for each chunk and collects all triples.
        """
        total = len(chunks)
        results: List[dict] = []

        for i, chunk in enumerate(chunks):
            extraction = self._invoke_with_backoff(chunk, i)
            if extraction and extraction.triples:
                for t in extraction.triples:
                    d = t.model_dump()
                    if not d.get("metadata"):
                        d["metadata"] = None
                    results.append(d)
            
            if(i+1)%10 == 0 or (i+1) == total:
                logger.info(f" [{i+1}/{total}] chunks done |"
                            f"{len(results)} triples accumulated")
                
        return results
    
    def _invoke_with_backoff(self, chunk: str, chunk_index: int) -> Optional[ExtractionResult]:
        """
        Invokes the LLM chain with:
        - A fixed post-call delay to stay within free-tier rate limits
        - Exponential backoff on 429 / quota errors.
        - MAX_RETRIES attempts before giving up on the chunk.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self._chain.invoke({"text": chunk})
                time.sleep(RATE_LIMIT_DELAY)
                return result
            
            except Exception as exc:
                err = str(exc).lower()
                is_quota = any(kw in err
                               for kw in ("429", "quota", "resource exhausted", "rate limit"))
                if is_quota:
                    wait = RETRY_BACKOFF * attempt
                    logger.warning(
                        f"Chunk {chunk_index} - quota hit"
                        f"Attempt {attempt}/{MAX_RETRIES})"
                        f"waiting {wait:.0f}s....."
                    )
                else:
                    logger.warning(f"Chunk {chunk_index} - non retryable error: {exc}"
                                   f"Attempt {attempt}/{MAX_RETRIES} - {exc}")
                    
                    return None
                
        logger.error(
            f"Chunk {chunk_index} - Exhausted {MAX_RETRIES} retries. Skipping"
        )

        return None
    
    @staticmethod
    def save(triples: List[dict], output_file: Path, source_name: str) -> None:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(triples, f, indent=4, ensure_ascii=False)
            logger.info(f"Saved {len(triples)} triples to {output_file.name}")
        except OSError as e:
            logger.error(f"Failed to write {output_file.name} for {source_name}: {e}")

