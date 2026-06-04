"""
src/ecograph/graphrag/Grounded_responder.py

Final cited answer synthesis for GraphRAG.

Combines:
1. Dense-retrieved community summaries (Qdrant)
2. Subgraph context (Neo4j neighbourhood)
3. Cypher-generated structured data
into a single, cited, grounded answer via the Groq LLM.

Every claim in the answer should trace back to one of the numbered
context sources so the answer is auditable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class GroundedAnswer:
    answer: str
    citations: list[dict]  # [{'source_id', text, score}]
    cypher_used: Optional[str]
    graph_records: list[dict]

# --------------------------------------------------------------------------
# Prompt template
# --------------------------------------------------------------------------

_SYSTEM = """
You are an ESG supply-chain analyst assistant. Answer the user question
using ONLY the context provided below. Do not invent any facts.
If the context does not contain enough information, say so explicitly.

After your answer, output a "Sources:" section listing the source IDs you used.
Use plain text. No markdown."""

_USER_TEMPLATE = """
Question: {question}

=== CONTEXT SOURCES ===
{context_block}

=== STRUCTURED DATA FROM GRAPH ===
{structured_data}

Please answer the question concisely (3-5 sentences) and cite the source IDs
from the context block."""

def _build_context_block(retrieved: list[dict]) -> str:
    lines = []
    for i, doc in enumerate(retrieved, 1):
        lines.append(f"[{i}] (score={doc.get('score', 0):.3f}) {doc.get('text', '')}")
    return "\n".join(lines) if lines else "No community context available."

def _build_structured_data(records: list[dict]) -> str:
    if not records:
        return "No graph records available."
    lines = []
    for r in records[:20]:
        lines.append(" " + str(r))
    return "\n".join(lines)

# --------------------------------------------------------------------------
# Main function
# --------------------------------------------------------------------------

def generate_grounded_answer(
    question: str,
    entity_ids: list[str],
    cypher: Optional[str] = None,
    neo4j_client=None,
    llm_client=None,
    vector_store=None,
    top_k: int = 5,
) -> GroundedAnswer:
    """
    Generate a cited, grounded answer to a supply-chain question.

    Parameters
    ----------
    question: Natural-language question from the user / agent.
    entity_ids: Supply-chain entities relevant to the question.
    cypher: Optional pre-translated Cypher to run for structured data.
    neo4j_client, llm_client, vector_store: Injectable dependencies.
    top_k: Number of community summaries to retrieve.

    Returns
    -------
    GroundedAnswer
    """
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
    from ecograph.llm import get_groq_client
    from ecograph.graphrag.vector_store import get_vector_store
    from ecograph.graphrag.subgraph_extractor import extract_subgraph

    db = neo4j_client or get_neo4j_client()
    llm = llm_client or get_groq_client()
    vs = vector_store or get_vector_store()

    # 1. Dense retrieval
    try:
        retrieved = vs.search(question, top_k=top_k)
    except Exception as exc:
        logger.warning("Vector store search failed: %s", exc)
        retrieved = []

    # 2. Subgraph context
    subgraph = extract_subgraph(entity_ids, hops=2, client=db)
    if subgraph.text_summary:
        retrieved.append({
            "doc_id": "subgraph",
            "text": subgraph.text_summary,
            "score": 1.0,
        })

    # 3. Optional structured Cypher query
    graph_records: list[dict] = []
    if cypher:
        try:
            graph_records = db.execute_read(cypher, {})
        except Exception as exc:
            logger.warning("Cypher query in grounded_responder failed: %s", exc)

    # 4. Build prompt
    context_block = _build_context_block(retrieved)
    structured_data = _build_structured_data(graph_records)
    prompt = _USER_TEMPLATE.format(
        question=question,
        context_block=context_block,
        structured_data=structured_data,
    )

    # 5. LLM call
    try:
        answer_text = llm.complete(prompt, system=_SYSTEM).strip()
    except Exception as exc:
        logger.error("LLM call in grounded_responder failed: %s", exc)
        answer_text = (
            "Unable to generate answer due to an LLM error. "
            "Please review the context sources directly."
        )

    citations = [
        {"source_id": f"[{i+1}]", "text": d.get("text", ""), "score": d.get("score", 0)}
        for i, d in enumerate(retrieved)
    ]

    return GroundedAnswer(
        answer=answer_text,
        citations=citations,
        cypher_used=cypher,
        graph_records=graph_records,
    )