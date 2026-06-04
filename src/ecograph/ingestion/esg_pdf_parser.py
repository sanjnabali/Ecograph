"""
src/ecograph/ingestion/esg_pdf_parser.py

Parses ESG sustainability PDF reports into structured graph triples using Groq.

Pipeline per PDF:
1. Extract text from PDF via pdfplumber (deterministic, no ML dependency).
2. Slide an overlapping window over the text - 8000 chars (~2000 tokens),
   500-char overlap, sentence-boundary aligned - to create chunks.
3. Estimate token count per chunk; skip or split chunks that would breach
   the Groq TPM ceiling to eliminate quota errors at source.
4. Call Groq (Llama-3.3-70b) with a schema-constrained extraction prompt.
5. Parse the returned JSON with four progressive fallbacks.
6. Filter by confidence threshold (default 0.70) and attach full provenance.
7. Return IngestionResult with triples, error accounting, and statistics.

Design decisions:
- Dependency injection: the constructor accepts ILLMClient, not a concrete
  GroqClient. Tests pass MockGroqClient; production uses get_groq_client().
  This satisfies the Dependency Inversion Principle and makes the class
  trivially testable without network access.
- Token pre-check before every Groq call prevents sending payloads that
  exceed TPM limits, drastically reducing 429 quota errors.
- Oversized chunks are split in half and processed recursively, so no
  content is silently dropped when chunk_size is misconfigured.
- Daily quota exhaustion aborts the current file immediately and propagates
  upward so the pipeline can schedule retries for the next day.
- Every triple carries a Provenance record (filename + chunk index + UTC
  timestamp) to satisfy CSRD / SB 253 auditability requirements.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from ecograph.config import settings
from ecograph.graph.schema import NodeLabel, RelationshipType
from ecograph.ingestion.base_ingestor import (
    BaseIngestor,
    GraphTriple,
    IngestionResult,
    NodeRef,
    Provenance,
)
from ecograph.llm import ILLMClient, LLMQuotaExhaustedError, LLMResponseError, get_groq_client

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------
# Prompts
# -----------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a precise structured data extraction engine for corporate ESG sustainability reports. "
    "Your output must always be a single valid JSON array and nothing else. "
    "Never include markdown code fences, preamble, or explanation outside the JSON. "
    "If no extractable facts are present, output exactly: []"
)

_EXTRACTION_PROMPT = """
Read the text chunk below. Extract ONLY verifiable, quantified, factual claims 
expressible as graph triples. Do not infer, estimate, or extrapolate beyond what 
is explicitly stated. Ignore promotional language, headings, and tables of contents.

Output ONLY a JSON array. Each element must strictly follow this schema:
{{
  "subject_name": "entity name exactly as written in the text",
  "subject_type": "Company | Supplier | Facility | Policy | Goal | Certification",
  "relationship": "HAS_GOAL | REPORTS_EMISSION | TARGETS_REDUCTION | CERTIFIED_BY | OPERATES | GOVERNED_BY",
  "object_name": "entity name exactly as written",
  "object_type": "EmissionTarget | GHGCategory | Scope | Certification | Facility | Regulation",
  "properties": {{
    "value": <number or null>,
    "unit": "tCO2e | MtCO2e | kgCO2e | % | year | null",
    "scope": <1 | 2 | 3 | null>,
    "category": <1-15 | null>,
    "target_year": <integer or null>,
    "baseline_year": <integer or null>
  }},
  "confidence": <float 0.0-1.0>,
  "source_sentence": "exact sentence this was derived from (max 200 chars)"
}}

TEXT CHUNK:
{chunk}

OUTPUT (JSON array only):"""


# -----------------------------------------------------------------
# Type and relationship maps
# -----------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "company": NodeLabel.COMPANY,
    "supplier": NodeLabel.SUPPLIER,
    "facility": NodeLabel.FACILITY,
    "region": NodeLabel.REGION,
    "policy": NodeLabel.REGULATION,
    "goal": NodeLabel.TARGET,
    "emissiontarget": NodeLabel.TARGET,
    "ghgcategory": NodeLabel.GHG_CATEGORY,
    "scope": NodeLabel.SCOPE,
    "certification": NodeLabel.CERTIFICATION,
    "regulation": NodeLabel.REGULATION,
}

_REL_MAP: dict[str, str] = {
    "has_goal": RelationshipType.SETS_TARGET,
    "reports_emission": RelationshipType.REPORTS_EMISSION,
    "targets_reduction": RelationshipType.SETS_TARGET,
    "certified_by": RelationshipType.CERTIFIED_BY,
    "operates": RelationshipType.OPERATES,
    "governed_by": RelationshipType.GOVERNED_BY,
}


def _map_type(type_str: str) -> str:
    key = type_str.lower().replace(" ", "").replace("_", "")
    return _TYPE_MAP.get(key, NodeLabel.COMPANY)


def _map_rel(rel_str: str) -> str:
    return _REL_MAP.get(rel_str.lower(), RelationshipType.REPORTS_EMISSION)


# -----------------------------------------------------------------
# JSON response parser (multi-stage fallback)
# -----------------------------------------------------------------

def _parse_llm_response(
    text: str,
    chunk_idx: int,
    debug_dir: Optional[Path] = None,
) -> list[dict]:
    """
    Parse LLM response text into a list of raw triple dicts.

    Four progressive fallbacks handle common LLM formatting deviations:
    1. Direct json.loads on stripped text (expected path).
    2. Strip markdown code fences then json.loads.
    3. Extract content between outermost [ ] brackets.
    4. Collect all { } objects and wrap in an array.
    """
    original = text
    text = text.strip()
    if not text:
        return []

    # Fallback 1: direct parse
    try:
        return _assert_list(json.loads(text), chunk_idx)
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback 2: strip markdown fences
    stripped = re.sub(r"^```(json)?\s*", "", text, flags=re.MULTILINE)
    stripped = re.sub(r"\s*```$", "", stripped, flags=re.MULTILINE).strip()
    if stripped and stripped != text:
        try:
            return _assert_list(json.loads(stripped), chunk_idx)
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback 3: extract outermost [ ... ]
    first, last = text.find("["), text.rfind("]")
    if first != -1 and last > first:
        try:
            return _assert_list(json.loads(text[first : last + 1]), chunk_idx)
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback 4: collect all { ... } objects
    objects = re.findall(r"\{[^{}]*\}", text, flags=re.DOTALL)
    if objects:
        try:
            return _assert_list(json.loads("[" + ", ".join(objects) + "]"), chunk_idx)
        except (json.JSONDecodeError, ValueError):
            pass

    # Write debug file for offline prompt analysis
    if debug_dir is not None:
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"llm_response_chunk_{chunk_idx}.txt").write_text(
                original, encoding="utf-8"
            )
        except OSError:
            pass

    raise ValueError(
        f"LLM response for chunk {chunk_idx} is not valid JSON after all fallbacks. "
        f"First 300 chars: {text[:300]}"
    )


def _assert_list(data: Any, chunk_idx: int) -> list[dict]:
    if not isinstance(data, list):
        raise ValueError(
            f"Expected JSON array for chunk {chunk_idx}, got {type(data).__name__}."
        )
    return [item for item in data if isinstance(item, dict)]


class ESGPDFParser(BaseIngestor):
    """
    Extracts structured graph triples from ESG sustainability PDF reports.
    Depends on ILLMClient (Groq in production, MockGroqClient in tests).
    """

    def __init__(
        self,
        llm_client: Optional[ILLMClient] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        min_confidence: Optional[float] = None,
    ) -> None:
        super().__init__(source_name="ESG_PDF")
        self.llm = llm_client if llm_client is not None else get_groq_client()
        self.chunk_size = (
            chunk_size if chunk_size is not None else settings.PDF_CHUNK_SIZE
        )
        self.chunk_overlap = (
            chunk_overlap if chunk_overlap is not None else settings.PDF_CHUNK_OVERLAP
        )
        self.min_confidence = (
            min_confidence
            if min_confidence is not None
            else settings.MIN_EXTRACTION_CONFIDENCE
        )
        self.debug_dir = settings.LOGS_DIR / "llm_debug"

    def ingest(self, filepath: str | Path, **kwargs: Any) -> IngestionResult:
        """
        Parse a single PDF and return extracted graph triples.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"ESG PDF not found: {filepath}")

        self._logger.info("Starting ESG PDF ingestion.", extra={"file": filepath.name})

        text = self._extract_text(filepath)
        if not text.strip():
            msg = f"{filepath.name}: no text extracted (image-only PDF?)"
            self._logger.warning(msg, extra={"file": filepath.name})
            return IngestionResult(triples=[], error_count=1, errors=[msg], source="ESG_PDF")

        chunks = self._chunk_text(text)
        self._logger.debug(
            "Text chunked.",
            extra={"file": filepath.name, "chunks": len(chunks), "chars": len(text)},
        )

        triples: list[GraphTriple] = []
        errors: list[str] = []
        skipped_quota = 0

        for idx, chunk in enumerate(chunks):
            try:
                raw_triples = self._extract_chunk(chunk, idx)
                for raw in raw_triples:
                    triple = self._build_triple(raw, filepath.name, idx)
                    if triple is not None:
                        triples.append(triple)
            except LLMQuotaExhaustedError as exc:
                skipped_quota += 1
                msg = f"{filepath.name} chunk {idx}: quota exhausted - {exc}"
                errors.append(msg)
                self._logger.warning(
                    "Groq quota exhausted; stopping remaining chunks.",
                    extra={
                        "file": filepath.name,
                        "chunk": idx,
                        "remaining": len(chunks) - idx,
                    },
                )
                break  # No point hammering a quota wall
            except LLMResponseError:
                raise  # Auth / bad model - propagate immediately
            except Exception as exc:
                msg = f"{filepath.name} chunk {idx}: {exc}"
                errors.append(msg)
                self._logger.debug("Chunk extraction failed: %s", msg)

        result = IngestionResult(
            triples=triples,
            error_count=len(errors),
            errors=errors,
            source="ESG_PDF",
        )
        self._logger.info(
            "ESG PDF ingestion complete.",
            extra={**result.summary(), "file": filepath.name, "skipped_quota_chunks": skipped_quota},
        )
        return result

    def ingest_directory(self, directory: str | Path) -> IngestionResult:
        """
        Parse all PDF files in a directory.
        Continues on per-file errors; stops immediately if daily Groq quota
        is exhausted (retrying subsequent files would fail identically).
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(f"ESG reports directory not found: {directory}")

        pdfs = sorted(directory.glob("*.pdf"))
        if not pdfs:
            self._logger.warning(
                "No PDF files found in directory.",
                extra={"directory": str(directory)},
            )
            return IngestionResult(triples=[], source="ESG_PDF")

        self._logger.info(
            "Ingesting ESG PDF directory.",
            extra={"directory": str(directory), "pdf_count": len(pdfs)},
        )
        all_triples: list[GraphTriple] = []
        all_errors: list[str] = []

        for pdf in pdfs:
            try:
                result = self.ingest(filepath=pdf)
                all_triples.extend(result.triples)
                all_errors.extend(result.errors)
            except LLMQuotaExhaustedError as exc:
                msg = f"Daily quota exhausted at {pdf.name}: {exc}. Stopping directory ingestion."
                all_errors.append(msg)
                self._logger.error(msg)
                break
            except (FileNotFoundError, RuntimeError) as exc:
                msg = f"File-level failure for {pdf.name}: {exc}"
                all_errors.append(msg)
                self._logger.error(msg)

        return IngestionResult(
            triples=all_triples,
            error_count=len(all_errors),
            errors=all_errors,
            source="ESG_PDF",
        )

    # -----------------------------------------------------------------
    # Text extraction
    # -----------------------------------------------------------------

    def _extract_text(self, filepath: Path) -> str:
        """
        Extract plain text from all content pages of a PDF using pdfplumber.

        Skips cover / TOC (first 2 pages) and tail legal / references
        (last 3 pages) via page-number heuristics.
        """
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError(
                "pdfplumber is required for PDF parsing. "
                "Install with: pip install pdfplumber"
            ) from exc

        try:
            pages_text: list[str] = []
            with pdfplumber.open(filepath) as pdf:
                total = len(pdf.pages)
                skip_head = min(2, total)
                skip_tail = max(0, total - 3)

                for page_num, page in enumerate(pdf.pages):
                    if page_num < skip_head or page_num >= skip_tail:
                        continue
                    try:
                        page_text = page.extract_text(x_tolerance=3, y_tolerance=3)
                        if page_text:
                            pages_text.append(page_text)
                    except Exception as exc:
                        self._logger.debug(
                            "Page extraction failed - skipping.",
                            extra={"file": filepath.name, "page": page_num, "error": str(exc)},
                        )

            return "\n\n".join(pages_text)
        except Exception as exc:
            raise RuntimeError(
                f"pdfplumber could not open '{filepath.name}': {exc}"
            ) from exc

    # -----------------------------------------------------------------
    # Chunking
    # -----------------------------------------------------------------

    def _chunk_text(self, text: str) -> list[str]:
        """
        Split text into overlapping fixed-size character windows.
        Attempts sentence-boundary alignment in the last 200 chars of each
        window. Discards chunks shorter than 100 chars (headers, footers).
        """
        chunks: list[str] = []
        start = 0
        length = len(text)

        while start < length:
            end = min(start + self.chunk_size, length)
            if end < length:
                zone = text[end - 200 : end]
                last_dot = zone.rfind(".")
                if last_dot != -1:
                    end = end - (200 - last_dot - 1)

            chunk = text[start:end].strip()
            if len(chunk) > 100:
                chunks.append(chunk)

            start = end - self.chunk_overlap
            if start < 0:
                start = 0
        return chunks

    def _extract_chunk(self, chunk: str, chunk_idx: int) -> list[dict]:
        # Pre-check tokens to prevent quota issues
        # (Simplified estimate: 4 chars ~ 1 token)
        if len(chunk) > 30000:
            logger.debug("Chunk too large, splitting.")
            mid = len(chunk) // 2
            return self._extract_chunk(chunk[:mid], chunk_idx) + self._extract_chunk(
                chunk[mid:], chunk_idx
            )

        prompt = _EXTRACTION_PROMPT.format(chunk=chunk)
        raw_response = self.llm.generate(
            system_prompt=_SYSTEM_PROMPT, user_prompt=prompt
        )
        return _parse_llm_response(raw_response, chunk_idx, debug_dir=self.debug_dir)

    def _build_triple(self, raw: dict, filename: str, chunk_idx: int) -> Optional[GraphTriple]:
        confidence = raw.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or confidence < self.min_confidence:
            return None

        # Map and validate components
        subject = NodeRef(
            name=raw.get("subject_name", ""),
            label=_map_type(raw.get("subject_type", "Company")),
        )
        obj = NodeRef(
            name=raw.get("object_name", ""),
            label=_map_type(raw.get("object_type", "Company")),
        )

        return GraphTriple(
            subject=subject,
            relationship=_map_rel(raw.get("relationship", "REPORTS_EMISSION")),
            object=obj,
            properties=raw.get("properties", {}),
            provenance=Provenance(
                source=filename,
                chunk_index=chunk_idx,
            ),
        )
    
    def _extract_chunk(self, chunk: str, chunk_idx: int) -> list[dict]:
        """
        Submit one text chunk to Groq for triple extraction.

        Splits oversized chunks (estimated tokens > 80% of TPM ceiling) in
        half and processes each half independently to avoid TPM breaches.

        Parameters
        ----------
        chunk:
            Text window to extract triples from.
        chunk_idx:
            Index used for logging and debug file naming.

        Returns
        -------
        list[dict]: Raw triple dicts.

        Raises
        ------
        LLMQuotaExhaustedError: Daily or per-minute quota exhausted.
        LLMResponseError: Non-retryable API error.
        ValueError: JSON parsing failed after all fallbacks.
        """
        estimated = self._llm.count_tokens(chunk) + settings.GROQ_MAX_TOKENS
        if estimated > settings.GROQ_TOKENS_PER_MINUTE * 0.8:
            self._logger.debug(
                "Chunk too large; splitting into halves.",
                extra={"chunk_idx": chunk_idx, "estimated_tokens": estimated},
            )
            mid = len(chunk) // 2
            return self._extract_chunk(chunk[:mid], chunk_idx) + \
                self._extract_chunk(chunk[mid:], chunk_idx)

        prompt = _EXTRACTION_PROMPT.replace("{chunk}", chunk)
        response_text = self._llm.complete(
            prompt,
            temperature=0.0,
            max_tokens=settings.GROQ_MAX_TOKENS,
            system_prompt=SYSTEM_PROMPT,
        )
        return _parse_llm_response(response_text, chunk_idx, self._debug_dir)

    # -----------------------------------------------------------------
    # Triple construction
    # -----------------------------------------------------------------

    def _build_triple(
        self,
        raw: dict,
        filename: str,
        chunk_idx: int,
    ) -> Optional[GraphTriple]:
        """
        Validate one raw extraction dict and convert it to a GraphTriple.

        Returns None for triples that are below confidence threshold or
        have missing required fields (subject, relationship, object).
        """
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        if confidence < self._min_confidence:
            return None

        subject_name = str(raw.get("subject_name", "")).strip()
        subject_type = str(raw.get("subject_type", "Company")).strip()
        relationship = str(raw.get("relationship", "")).strip()
        object_name = str(raw.get("object_name", "")).strip()
        object_type = str(raw.get("object_type", "Entity")).strip()

        if not subject_name or not relationship or not object_name:
            self._logger.debug(
                "Skipping triple with missing required fields.",
                extra={"raw_preview": str(raw)[:200]},
            )
            return None

        raw_props = raw.get("properties", {}) or {}
        properties: dict[str, Any] = {}
        for key in ("value", "unit", "scope", "category", "target_year", "baseline_year"):
            val = raw_props.get(key)
            if val is not None and str(val).strip() not in ("", "null", "None"):
                properties[key] = val
        
        source_sentence = str(raw.get("source_sentence", "")).strip()
        if source_sentence:
            properties["source_sentence"] = source_sentence[:300]

        return self._triple(
            subject=self._node(label=map_type(subject_type), name=subject_name),
            relationship=map_rel(relationship),
            obj=self._node(label=map_type(object_type), name=object_name),
            properties=properties,
            provenance=Provenance(source="ESG_PDF", file=filename, chunk_index=chunk_idx,
            confidence=confidence,
            )
        )

    # -----------------------------------------------------------------
    # Text extraction
    # -----------------------------------------------------------------

    def _extract_text(self, filepath: Path) -> str:
        """
        Extract plain text from a PDF using pdfplumber.

        Skips pages that are clearly non-content (cover, TOC, legal boilerplate)
        based on page number heuristics. Pages 1 and 2 are skipped (cover + TOC).
        The last 3 pages are skipped (references, legal).
        """
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError(
                "pdfplumber is required for PDF parsing. "
                "Install with: pip install pdfplumber"
            ) from exc

        try:
            pages_text: list[str] = []
            with pdfplumber.open(filepath) as pdf:
                total = len(pdf.pages)
                # Skip cover/TOC (pages 0-1) and tail (last 3 pages)
                skip_head = min(2, total)
                skip_tail = max(0, total - 3)

                for page_num, page in enumerate(pdf.pages):
                    if page_num < skip_head:
                        continue
                    if page_num >= skip_tail:
                        continue
                    try:
                        page_text = page.extract_text(x_tolerance=3, y_tolerance=3)
                        if page_text:
                            pages_text.append(page_text)
                    except Exception as exc:
                        self._logger.debug(
                            "Page extraction failed, skipping.",
                            extra={"page": page_num, "error": str(exc)},
                        )

                return "\n\n".join(pages_text)
        except Exception as exc:
            raise RuntimeError(
                f"pdfplumber failed to open '{filepath.name}': {exc}"
            ) from exc
    