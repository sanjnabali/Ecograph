"""
src/ecograph/ingestion/esg_pdf_parser.py

Parses ESG sustainability PDF reports into graph triples using Gemini.

Pipeline per PDF:
  1. Extract text from PDF via pdfplumber (deterministic, no ML dependency)
  2. Slide an overlapping window over the text to create chunks
  3. For each chunk, call Gemini with a schema-constrained extraction prompt
  4. Validate and filter the returned JSON array
  5. Attach provenance (filename + chunk index) to every triple
  6. Return IngestionResult with all triples and error accounting

Design decisions:
- pdfplumber over PyMuPDF or pdfminer: it handles tables and multi-column
  layouts better for corporate ESG reports, and is BSD-licensed.
- Chunking by character count (not token count) avoids a tokeniser dependency
  and is stable across model versions. 8000 chars is approximately 2000 tokens
  for English text, comfortably within Gemini Flash's context.
- 500-char overlap prevents facts that straddle chunk boundaries from being
  silently dropped.
- The extraction prompt forces JSON-only output with a fixed schema. Any
  response that is not valid JSON is logged and counted as an error — the
  chunk is not retried (quota is expensive) but the run continues.
- Confidence threshold (default 0.70) is applied after extraction, not inside
  the prompt, so we can tune it without re-running LLM calls.
- Gemini rate limiting: free tier is 15 RPM. We sleep RATE_LIMIT_DELAY seconds
  between calls. On failure with a quota error (429) we back off exponentially
  up to MAX_RETRIES attempts.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import google.generativeai as genai

from ecograph.config import settings
from ecograph.graph.schema import NodeLabel, RelationshipType
from ecograph.ingestion.base_ingestor import (
    BaseIngestor,
    GraphTriple,
    IngestionResult,
    NodeRef,
    Provenance,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
You are a structured data extraction engine for ESG sustainability reports.

Read the text chunk below and extract ONLY verifiable, quantified, factual \
claims that can be expressed as graph triples. Do not infer, estimate, or \
extrapolate beyond what is explicitly stated.

Output ONLY a JSON array. No preamble, no markdown, no explanation.
If no extractable facts are present, output an empty array: []

Each element must strictly follow this schema:
{
  "subject_name": "entity name exactly as written in the text",
  "subject_type": "Company | Supplier | Facility | Policy | Goal | Certification",
  "relationship": "HAS_GOAL | REPORTS_EMISSION | TARGETS_REDUCTION | CERTIFIED_BY | OPERATES | GOVERNED_BY",
  "object_name": "entity name exactly as written",
  "object_type": "EmissionTarget | GHGCategory | Scope | Certification | Facility | Regulation",
  "properties": {
    "value": <number or null>,
    "unit": "tCO2e | MtCO2e | kgCO2e | % | year | null",
    "scope": <1 | 2 | 3 | null>,
    "category": <1-15 or null>,
    "target_year": <integer or null>,
    "baseline_year": <integer or null>
  },
  "confidence": <float 0.0-1.0>,
  "source_sentence": "exact sentence this was derived from (max 200 chars)"
}

TEXT CHUNK:
{chunk}

OUTPUT (JSON array only):"""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ESGPDFParser(BaseIngestor):
    """
    Extracts graph triples from ESG sustainability PDF reports.

    Usage:
        parser = ESGPDFParser()
        result = parser.ingest(filepath="data/raw/esg_reports/apple_epr_2023.pdf")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        min_confidence: Optional[float] = None,
    ) -> None:
        super().__init__(source_name="ESG_PDF")

        api_key = api_key or settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY in .env "
                "or pass api_key= to ESGPDFParser()."
            )

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model or settings.GEMINI_MODEL)
        self._chunk_size    = chunk_size    or settings.PDF_CHUNK_SIZE
        self._chunk_overlap = chunk_overlap or settings.PDF_CHUNK_OVERLAP
        self._min_confidence = (
            min_confidence
            if min_confidence is not None
            else settings.MIN_EXTRACTION_CONFIDENCE
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def ingest(self, filepath: str | Path, **kwargs: Any) -> IngestionResult:
        """
        Parse a single PDF and return extracted triples.

        Parameters
        ----------
        filepath : path to the PDF file.

        Returns
        -------
        IngestionResult

        Raises
        ------
        FileNotFoundError : if the PDF does not exist.
        RuntimeError : if pdfplumber cannot open the file (corrupt PDF).
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(
                f"ESG PDF not found: {filepath}"
            )

        self._logger.info(
            "Starting ESG PDF ingestion.",
            extra={"file": filepath.name},
        )

        text = self._extract_text(filepath)
        if not text.strip():
            self._logger.warning(
                "PDF produced no extractable text. It may be scanned/image-based.",
                extra={"file": filepath.name},
            )
            return IngestionResult(
                triples=[],
                error_count=1,
                errors=[f"{filepath.name}: no text extracted (image PDF?)"],
                source="ESG_PDF",
            )

        chunks = self._chunk_text(text)
        self._logger.debug(
            "Text chunked.",
            extra={"file": filepath.name, "chunks": len(chunks), "text_chars": len(text)},
        )

        triples: list[GraphTriple] = []
        errors: list[str] = []

        for chunk_idx, chunk in enumerate(chunks):
            try:
                raw_triples = self._extract_triples(chunk, chunk_idx)
                for raw in raw_triples:
                    triple = self._build_triple(raw, filepath.name, chunk_idx)
                    if triple is not None:
                        triples.append(triple)
            except Exception as exc:
                msg = f"{filepath.name} chunk {chunk_idx}: {exc}"
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
            extra={**result.summary(), "file": filepath.name},
        )
        return result

    def ingest_directory(self, directory: str | Path) -> IngestionResult:
        """
        Parse all PDF files in a directory.

        Returns a merged IngestionResult across all files.
        Continues on per-file failures — one bad PDF does not abort the rest.
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

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

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
                "Install it with: pip install pdfplumber"
            ) from exc

        try:
            pages_text: list[str] = []
            with pdfplumber.open(filepath) as pdf:
                total = len(pdf.pages)
                # Skip cover/TOC (pages 0–1) and tail (last 3 pages)
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

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> list[str]:
        """
        Split text into overlapping fixed-size character windows.

        Tries to split at sentence boundaries ('. ') within the last
        200 characters of each chunk to avoid cutting mid-sentence.
        """
        chunks: list[str] = []
        start = 0
        length = len(text)

        while start < length:
            end = min(start + self._chunk_size, length)

            # Try to break at a sentence boundary in the tail
            if end < length:
                search_zone = text[end - 200: end]
                last_period = search_zone.rfind(". ")
                if last_period != -1:
                    end = end - 200 + last_period + 2  # include ". "

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Move start forward by chunk_size minus overlap
            start += self._chunk_size - self._chunk_overlap

        return chunks

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def _extract_triples(self, chunk: str, chunk_idx: int) -> list[dict]:
        """
        Call Gemini to extract facts from one text chunk.

        Implements exponential back-off retry for quota errors (429).
        Returns a list of raw triple dicts, or raises on unrecoverable error.
        """
        prompt = _EXTRACTION_PROMPT.format(chunk=chunk)
        last_exc: Optional[Exception] = None

        for attempt in range(1, settings.MAX_RETRIES + 1):
            try:
                response = self._model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.0,              # deterministic extraction
                        max_output_tokens=settings.GEMINI_MAX_TOKENS,
                    ),
                )
                time.sleep(settings.RATE_LIMIT_DELAY)
                return self._parse_response(response.text, chunk_idx)

            except Exception as exc:
                last_exc = exc
                err_str = str(exc).lower()
                is_quota = any(
                    kw in err_str
                    for kw in ("429", "quota", "resource_exhausted", "rate limit")
                )
                if is_quota:
                    wait = settings.RETRY_BACKOFF * (2 ** (attempt - 1))
                    self._logger.warning(
                        "Gemini quota hit, backing off.",
                        extra={"attempt": attempt, "wait_seconds": wait},
                    )
                    time.sleep(wait)
                else:
                    # Non-quota error — no point retrying
                    raise RuntimeError(
                        f"Gemini call failed (chunk {chunk_idx}): {exc}"
                    ) from exc

        raise RuntimeError(
            f"Gemini exhausted {settings.MAX_RETRIES} retries "
            f"(chunk {chunk_idx}). Last error: {last_exc}"
        )

    @staticmethod
    def _parse_response(response_text: str, chunk_idx: int) -> list[dict]:
        """
        Parse the LLM response into a list of raw dicts.

        Handles:
        - Bare JSON arrays (expected)
        - JSON wrapped in markdown code fences (common LLM habit)
        - Completely empty responses (returns [])

        Raises:
            ValueError : if the response cannot be parsed as JSON.
        """
        text = response_text.strip()
        if not text:
            return []

        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
        text = text.strip()

        if not text or text == "[]":
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Gemini response is not valid JSON "
                f"(chunk {chunk_idx}): {exc}. "
                f"Response (first 200 chars): {text[:200]}"
            ) from exc

        if not isinstance(data, list):
            raise ValueError(
                f"Gemini response is not a JSON array "
                f"(chunk {chunk_idx}). Got: {type(data).__name__}"
            )

        return data

    # ------------------------------------------------------------------
    # Triple construction
    # ------------------------------------------------------------------

    def _build_triple(
        self,
        raw: dict,
        filename: str,
        chunk_idx: int,
    ) -> Optional[GraphTriple]:
        """
        Convert one raw extraction dict into a validated GraphTriple.

        Returns None (and logs a debug message) if:
        - Confidence is below threshold
        - Required fields are missing or empty
        - Subject or object names are blank
        """
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        if confidence < self._min_confidence:
            return None

        subject_name = str(raw.get("subject_name", "")).strip()
        subject_type = str(raw.get("subject_type", "Company")).strip()
        relationship  = str(raw.get("relationship", "")).strip()
        object_name   = str(raw.get("object_name", "")).strip()
        object_type   = str(raw.get("object_type", "Entity")).strip()

        if not subject_name or not relationship or not object_name:
            self._logger.debug(
                "Skipping triple with empty required fields.",
                extra={"raw": str(raw)[:200]},
            )
            return None

        # Map ESG extraction types to schema NodeLabel constants
        subject_label = self._map_type_to_label(subject_type)
        object_label  = self._map_type_to_label(object_type)
        rel_type      = self._map_relationship(relationship)

        # Build properties — filter None values
        raw_props = raw.get("properties", {}) or {}
        properties: dict = {}
        for key in ("value", "unit", "scope", "category", "target_year", "baseline_year"):
            val = raw_props.get(key)
            if val is not None and str(val).strip() not in ("", "null", "None"):
                properties[key] = val

        # Attach source sentence as provenance detail
        source_sentence = str(raw.get("source_sentence", "")).strip()
        if source_sentence:
            properties["source_sentence"] = source_sentence[:300]

        subject_node = self._node(
            label=subject_label,
            name=subject_name,
        )
        object_node = self._node(
            label=object_label,
            name=object_name,
        )
        provenance = Provenance(
            source="ESG_PDF",
            file=filename,
            chunk_index=chunk_idx,
        )

        return self._triple(
            subject=subject_node,
            relationship=rel_type,
            obj=object_node,
            properties=properties,
            provenance=provenance,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Type mapping
    # ------------------------------------------------------------------

    _TYPE_MAP: dict[str, str] = {
        "company":       NodeLabel.COMPANY,
        "supplier":      NodeLabel.SUPPLIER,
        "facility":      NodeLabel.FACILITY,
        "region":        NodeLabel.REGION,
        "policy":        NodeLabel.REGULATION,
        "goal":          NodeLabel.TARGET,
        "emissiontarget": NodeLabel.TARGET,
        "ghgcategory":   NodeLabel.GHG_CATEGORY,
        "scope":         NodeLabel.SCOPE,
        "certification": NodeLabel.CERTIFICATION,
        "regulation":    NodeLabel.REGULATION,
    }

    _REL_MAP: dict[str, str] = {
        "has_goal":           RelationshipType.SETS_TARGET,
        "reports_emission":   RelationshipType.REPORTS_EMISSION,
        "targets_reduction":  RelationshipType.SETS_TARGET,
        "certified_by":       RelationshipType.CERTIFIED_BY,
        "operates":           RelationshipType.OPERATES,
        "governed_by":        RelationshipType.GOVERNED_BY,
    }

    @classmethod
    def _map_type_to_label(cls, type_str: str) -> str:
        key = type_str.lower().replace(" ", "").replace("_", "")
        return cls._TYPE_MAP.get(key, NodeLabel.COMPANY)

    @classmethod
    def _map_relationship(cls, rel_str: str) -> str:
        key = rel_str.lower()
        return cls._REL_MAP.get(key, RelationshipType.REPORTS_EMISSION)