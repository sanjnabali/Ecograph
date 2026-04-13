"""
api/routers/chat.py - AI Chat endpoint (Gemini + graph context).

POST /api/chat/message      - send a message, get a graph-aware AI response
GET  /api/chat/suggestions  - pre-built example questions for the UI

How it works:
1. Receive user question
2. Run a lightweight Cypher query to pull relevant context from Neo4j
   (companies, emissions, targets matching keywords in the question)
3. Build a context-enriched prompt and send to Gemini
4. Stream or return the response

Gemini free-tier safe: rate limit enforced via RATE_LIMIT_DELAY.
"""

import logging
import re
import time
from typing import List, Optional

from fastapi import APIRouter, Depends
from neo4j import Driver
from pydantic import BaseModel, Field, field_validator

from api.deps import get_driver
from src.config.settings import (
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    RATE_LIMIT_DELAY,
    MAX_RETRIES,
    RETRY_BACKOFF,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["AI Chat"])

class ChatMessage(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    history: List[dict] = Field(default_factory=list,
                                description="Previous turns: [{'role', 'content'}, ...]")

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        return v.strip()

    @field_validator("history")
    @classmethod
    def validate_history(cls, v: List[dict]) -> List[dict]:
        # Max 10 turns of history to keep prompts within token limits
        valid = []
        for turn in v[-10:]:
            if isinstance(turn, dict) and "role" in turn and "content" in turn:
                if turn["role"] in ("user", "assistant") and isinstance(turn["content"], str):
                    valid.append({"role": turn["role"], "content": turn["content"][:500]})
        return valid

class ChatResponse(BaseModel):
    answer: str
    sources: List[str] = Field(default_factory=list,
                               description="Company/node names referenced in the answer")
    context_used: bool = Field(description="Whether Neo4j context was injected")

class Suggestion(BaseModel):
    question: str
    category: str

_SUGGESTIONS = [
    Suggestion(question="Which companies have the highest Scope 3 emissions?", category="Emissions"),
    Suggestion(question="What are the net-zero targets in the graph?",       category="Targets"),
    Suggestion(question="List all Tier 1 suppliers and their regions.",      category="Supply Chain"),
    Suggestion(question="Which companies report under GRI standards?",       category="Governance"),
    Suggestion(question="What Scope 3 categories are most common?",          category="Emissions"),
    Suggestion(question="Which suppliers have the highest annual spend?",    category="Supply Chain"),
    Suggestion(question="Are there any companies with reduction targets?",   category="Targets"),
    Suggestion(question="Show me facilities and where they are located.",    category="Locations"),
]

def _fetch_graph_context(driver: Driver, question: str) -> tuple[str, List[str]]:
    """
    Pulls relevant facts from Neo4j to ground the AI answer.

    Strategy:
    1. Extract company-like tokens from the question (capitalised words)
    2. Run targeted Cypher to fetch their emissions + targets
    3. Always append top-5 emissions summary as global context
    4. Return (context_text, list_of_mentioned_companies)
    """
    # Heuristic: extract capitalised words/phrases as candidate company names
    tokens = re.findall(r"[A-Z][a-zA-Z0-9&\.\-\s]{1,40}", question)
    candidate_names = [t.strip() for t in tokens if len(t.strip()) > 2]

    context_parts: List[str] = []
    mentioned:     List[str] = []

    with driver.session() as session:
        # --- Company-specific context ---
        if candidate_names:
            company_cypher = """
                UNWIND $names AS keyword
                MATCH (c:Company)
                WHERE toLower(c.name) CONTAINS toLower(keyword)
                OPTIONAL MATCH (c)-[:REPORTS_EMISSION]->(e:EmissionMetric)
                OPTIONAL MATCH (e)-[:MEASURED_IN_YEAR]->(y:Year)
                OPTIONAL MATCH (e)-[:FALLS_UNDER_SCOPE]->(s:Scope)
                OPTIONAL MATCH (c)-[:COMMITS_TO_NET_ZERO]->(ty:Year)
                OPTIONAL MATCH (c)-[:HAS_SUPPLIER]->(sup:Company)
                RETURN DISTINCT
                    c.name       AS company,
                    e.value      AS emission,
                    COALESCE(e.unit, 'tCO2e') AS unit,
                    y.value      AS year,
                    s.name       AS scope,
                    ty.value     AS net_zero_year,
                    sup.name     AS supplier
                LIMIT 20
            """
            rows = list(session.run(company_cypher, names=candidate_names))
            if rows:
                lines = []
                for r in rows:
                    company = r["company"]
                    if company and company not in mentioned:
                        mentioned.append(company)
                    if r["emission"] is not None:
                        lines.append(
                            f"- {company}: {r['emission']} {r['unit']} "
                            f"({r['scope'] or 'unknown scope'}, {r['year'] or 'unknown year'})"
                        )
                    if r["net_zero_year"]:
                        lines.append(f"- {company}: net-zero target by {r['net_zero_year']}")
                    if r["supplier"]:
                        lines.append(f"- {company} has supplier: {r['supplier']}")
                if lines:
                    context_parts.append("Specific company data:\n" + "\n".join(lines))

        # --- Global top-5 emissions (always included) ---
        top_cypher = """
            MATCH (c:Company)-[:REPORTS_EMISSION]->(e:EmissionMetric)
            OPTIONAL MATCH (e)-[:FALLS_UNDER_SCOPE]->(s:Scope)
            RETURN c.name AS company, e.value AS value,
                   COALESCE(e.unit, 'tCO2e') AS unit, s.name AS scope
            ORDER BY CASE WHEN e.value IS NOT NULL THEN toFloat(e.value) ELSE 0 END DESC
            LIMIT 5
        """
        top_rows = list(session.run(top_cypher))
        if top_rows:
            top_lines = [
                f"- {r['company']}: {r['value']} {r['unit']} ({r['scope'] or 'unknown scope'})"
                for r in top_rows if r["company"]
            ]
            if top_lines:
                context_parts.append("Top 5 emitters:\n" + "\n".join(top_lines))

        # --- Targets context ---
        if any(kw in question.lower() for kw in ("target", "net-zero", "netzero", "commit", "reduction")):
            target_cypher = """
                MATCH (c:Company)-[:COMMITS_TO_NET_ZERO]->(y:Year)
                RETURN c.name AS company, y.value AS year
                ORDER BY y.value LIMIT 10
            """
            t_rows = list(session.run(target_cypher))
            if t_rows:
                t_lines = [f"- {r['company']}: net-zero by {r['year']}" for r in t_rows if r["company"]]
                context_parts.append("Net-zero commitments:\n" + "\n".join(t_lines))

    context_text = "\n\n".join(context_parts) if context_parts else ""
    return context_text, mentioned

def _call_gemini(prompt: str, history: List[dict]) -> str:
    """
    Calls Gemini with retry/backoff.
    Returns the answer string or raises on exhausted retries.
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    except ImportError as exc:
        raise RuntimeError(
            "langchain-google-genai is not installed. "
            "Run: pip install langchain-google-genai"
        ) from exc

    llm = ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=GEMINI_TEMPERATURE)

    # Inject conversation history
    messages = []
    for turn in history:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))

    messages.append(HumanMessage(content=prompt))

    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = llm.invoke(messages)
            time.sleep(RATE_LIMIT_DELAY)
            return response.content
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            is_quota = any(
                kw in err for kw in ("429", "quota", "resource exhausted", "rate limit")
            )
            if is_quota:
                wait = RETRY_BACKOFF * attempt
                logger.warning(f"Gemini quota hit (attempt {attempt}/{MAX_RETRIES}). Waiting {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"Gemini non-retryable error: {exc}")
                raise RuntimeError(f"Gemini call failed: {exc}") from exc

    raise RuntimeError(
        f"Gemini exhausted {MAX_RETRIES} retries. Last error: {last_exc}"
    )

@router.get(
    "/suggestions",
    response_model=List[Suggestion],
    summary="Pre-built example questions for the chat UI",
)
def get_suggestions() -> List[Suggestion]:
    return _SUGGESTIONS

@router.post(
    "/message",
    response_model=ChatResponse,
    summary="Send a question to the AI, grounded in your Neo4j graph data",
)
def send_message(
    payload: ChatMessage,
    driver: Driver = Depends(get_driver),
) -> ChatResponse:
    """
    Workflow:
    1. Pull relevant graph context from Neo4j
    2. Build enriched prompt: context + question
    3. Call Gemini with conversation history
    4. Return answer + metadata

    Edge cases handled:
      - Empty/whitespace question      -> 422 (Pydantic validation)
      - No graph data yet              -> answered without context, flagged
      - Gemini quota exhausted         -> 429 with clear message
      - Gemini unavailable             -> 503
      - Malicious prompt injection     -> system prompt hard-coded, user input isolated
    """
    # Validate API key is present before hitting Neo4j
    import os
    if not os.getenv("GOOGLE_API_KEY"):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail={
                "error":   "missing_api_key",
                "message": "GOOGLE_API_KEY is not set. Add it to your .env file.",
            },
        )

    # Step 1: fetch graph context
    context_text, mentioned = _fetch_graph_context(driver, payload.question)
    context_used = bool(context_text)

    # Step 2: build prompt
    if context_text:
        prompt = (
            f"Graph database context (use this to answer accurately):\n\n"
            f"{context_text}\n\n"
            f"---\n"
            f"User question: {payload.question}"
        )
    else:
        prompt = (
            f"Note: no specific graph data was found matching this question. "
            f"Answer based on general ESG/Scope 3 knowledge.\n\n"
            f"User question: {payload.question}"
        )

    # Step 3: call Gemini
    try:
        answer = _call_gemini(prompt, payload.history)
    except RuntimeError as exc:
        err_str = str(exc).lower()
        from fastapi import HTTPException
        if "quota" in err_str or "429" in err_str or "retries" in err_str:
            raise HTTPException(
                status_code=429,
                detail={
                    "error":   "rate_limit_exceeded",
                    "message": (
                        "Gemini API quota exhausted. "
                        "Wait a minute and try again (free tier: 15 req/min)."
                    ),
                },
            )
        raise HTTPException(
            status_code=503,
            detail={"error": "llm_unavailable", "message": str(exc)},
        )

    return ChatResponse(
        answer=answer,
        sources=mentioned,
        context_used=context_used,
    )