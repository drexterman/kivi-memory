from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.db.database import get_connection
from app.memory.provenance import memory_trace
from app.memory.retriever import retrieve_evidence_bundle, retrieve_memories, retrieve_related_memories

load_dotenv()


class EvidenceJudgment(BaseModel):
    verdict: Literal["SUPPORTED", "CONTRADICTED", "UNCERTAIN", "UNSUPPORTED"]
    reason: str = Field(min_length=1)


JUDGE_INSTRUCTIONS = """
You are the evidence judge for Hey Kivi, a personal semantic-memory assistant.

Use ONLY the supplied memory records, memory history, and transcript evidence.
Do not use world knowledge and do not fill gaps with assumptions.

State rules:
- ACTIVE is the current established state.
- SUPERSEDED is historical and must not be treated as current.
- UNCERTAIN is pending/ambiguous and must not be presented as established.
- A memory is relevant only if it actually bears on the question.
- Entity overlap alone is not enough.
- If the supplied evidence does not answer the question, verdict UNSUPPORTED.
- If the question asks about a specific value and current evidence establishes a
  different value, verdict CONTRADICTED.
- If the only evidence for the requested state is UNCERTAIN, verdict UNCERTAIN.
- For WHY/REASON questions, a historical memory or transcript may explain a current
  state, but do not invent a reason that is not present in the evidence.
- For DECISION questions, use decision/episode/history evidence when available.
- For property questions (database, technology, deployment, etc.), ignore vague
  placeholder values such as "existing database setup" when concrete evidence exists.
- A SUPERSEDED memory is historical evidence only; use timestamps/source wording to
  reason about what was current, and never call a vague placeholder authoritative.
- Never use resolver/history implementation reasons such as "Created from transcript
  after candidate validation" as the user's answer.

Return only the structured verdict and a concise reason.
"""


def _memory_evidence(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for m in memories:
        trace = memory_trace(m["id"])
        result.append({
            "memory_id": m["id"],
            "type": m["type"],
            "status": m["status"],
            "subject": m["subject"],
            "title": m["title"],
            "content": m["content"],
            "retrieval_score": m.get("retrieval_score"),
            "retrieval_debug": m.get("retrieval_debug"),
            "sources": [
                {
                    "transcript_id": x["transcript_id"],
                    "timestamp": x.get("timestamp"),
                    "evidence": x["evidence"],
                    "formatted_text": x.get("formatted_text"),
                }
                for x in trace.get("sources", [])
            ],
            "provenance": [
                {
                    "transcript_id": x["transcript_id"],
                    "evidence": x["evidence"],
                    "timestamp": x.get("timestamp"),
                }
                for x in trace.get("sources", [])
            ],
            "history": [
                {
                    "event_type": x["event_type"],
                    "old_value": x.get("old_value"),
                    "new_value": x.get("new_value"),
                    "reason": x.get("reason"),
                    "source_transcript_id": x.get("source_transcript_id"),
                }
                for x in trace.get("history", [])
            ],
        })
    return result


def _question_terms(question: str) -> list[str]:
    return [
        x for x in re.findall(r"[a-z0-9][a-z0-9_-]+", question.lower())
        if len(x) > 2
    ]


def _is_vague_value(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "existing database setup",
        "current database setup",
        "existing setup",
        "current setup",
        "the existing database",
        "the current database",
        "same setup",
        "existing datastore",
    }


def _memory_attribute(memory: dict[str, Any]) -> str:
    return str((memory.get("content") or {}).get("attribute") or "").strip().lower()


def _property_question(question: str) -> str | None:
    q = question.lower()
    if "database" in q or "data store" in q or "datastore" in q:
        return "database"
    if any(x in q for x in ("technology", "tech", "stack", "platform")):
        return "technology"
    if "deployment" in q or "deployed" in q:
        return "deployment"
    return None


def _direct_sources(memory: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for source in memory.get("sources") or []:
        text = str(source.get("evidence") or source.get("formatted_text") or "").strip()
        if text:
            out.append(text)
    return out


def _fallback_judge(question: str, memories: list[dict[str, Any]]) -> EvidenceJudgment:
    if not memories:
        return EvidenceJudgment(
            verdict="UNSUPPORTED",
            reason="No relevant memory evidence was retrieved.",
        )

    q = question.lower()
    prop = _property_question(question)
    requested = next(
        (
            x for x in (
                "postgresql", "postgres", "duckdb", "sqlite", "redis",
                "kafka", "valkey", "mysql", "mongodb",
            )
            if x in q
        ),
        None,
    )

    relevant = memories
    if prop:
        relevant = [
            m for m in memories
            if _memory_attribute(m) == prop
            or _memory_attribute(m) in {
                "db", "datastore", "data store", "storage", "store"
            }
        ]
        relevant = [m for m in relevant if not _is_vague_value((m.get("content") or {}).get("value"))]

    active = [m for m in relevant if m.get("status") == "ACTIVE"]
    uncertain = [m for m in relevant if m.get("status") == "UNCERTAIN"]

    if requested:
        requested_norm = "postgresql" if requested == "postgres" else requested
        for m in active:
            value = str((m.get("content") or {}).get("value") or "").lower().strip()
            value_norm = "postgresql" if value == "postgres" else value
            if value_norm == requested_norm:
                return EvidenceJudgment(
                    verdict="SUPPORTED",
                    reason="An active memory explicitly contains the requested value.",
                )
        for m in active:
            value = str((m.get("content") or {}).get("value") or "").strip()
            if value and not _is_vague_value(value):
                return EvidenceJudgment(
                    verdict="CONTRADICTED",
                    reason=f"The relevant active memory establishes {value} instead.",
                )
        if uncertain:
            return EvidenceJudgment(
                verdict="UNCERTAIN",
                reason="Only uncertain memory evidence was found for the requested state.",
            )

    if not relevant:
        return EvidenceJudgment(
            verdict="UNSUPPORTED",
            reason="No memory directly addresses the requested property.",
        )

    # Never claim support for a decision/reason/person question merely because an
    # entity was retrieved. Require actual source/episode evidence.
    if "decision" in q or "decided" in q or "did we" in q:
        for m in relevant:
            if m.get("type") == "EPISODE" and _direct_sources(m):
                return EvidenceJudgment(
                    verdict="SUPPORTED",
                    reason="A source-backed episode directly addresses the decision.",
                )
        return EvidenceJudgment(verdict="UNSUPPORTED", reason="No source-backed decision evidence was found.")

    if "why" in q or "reason" in q:
        if any("because" in text.lower() or "reason" in text.lower() for m in relevant for text in _direct_sources(m)):
            return EvidenceJudgment(
                verdict="SUPPORTED",
                reason="A transcript directly provides the requested reason.",
            )
        return EvidenceJudgment(verdict="UNSUPPORTED", reason="No explicit causal evidence was found.")

    return EvidenceJudgment(
        verdict="SUPPORTED" if active else ("UNCERTAIN" if uncertain else "UNSUPPORTED"),
        reason="Relevant memory evidence was retrieved.",
    )


def _judge_with_openrouter(
    question: str,
    evidence: list[dict[str, Any]],
) -> tuple[EvidenceJudgment, dict[str, Any]]:
    from openai import OpenAI

    api_key = os.getenv("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY is not configured")

    base_url = os.getenv(
        "BASE_URL",
        "https://openrouter.ai/api/v1",
    )
    model = os.getenv(
        "MODEL",
        "mistralai/mistral-small-3.2-24b-instruct:free",
    )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    schema = EvidenceJudgment.model_json_schema()

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "evidence_judgment",
                "schema": schema,
                "strict": True,
            },
        },
        messages=[
            {"role": "system", "content": JUDGE_INSTRUCTIONS},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "memory_evidence": evidence,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )

    text = response.choices[0].message.content or ""
    judgment = EvidenceJudgment.model_validate_json(text)
    usage = getattr(response, "usage", None)

    return judgment, {
        "provider": "OpenRouter",
        "model": model,
        "response_id": getattr(response, "id", None),
        "usage": usage.model_dump() if hasattr(usage, "model_dump") else (dict(usage) if usage else None),
    }


def _deterministic_property_judge(
    question: str,
    memories: list[dict[str, Any]],
) -> EvidenceJudgment | None:
    """Resolve simple property lookups without an LLM.

    Property questions are state lookups, so an LLM should not be allowed to
    reinterpret a concrete ACTIVE value as a contradiction merely because a
    superseded historical value is also present in the evidence bundle.
    """
    prop = _property_question(question)
    if not prop:
        return None

    q = question.lower()
    requested = next(
        (
            x for x in (
                "postgresql", "postgres", "duckdb", "sqlite", "redis",
                "kafka", "valkey", "mysql", "mongodb",
            )
            if x in q
        ),
        None,
    )

    # Database/data-store and technology questions share the same concrete
    # storage technology evidence. Deployment remains its own property.
    allowed_attributes = {
        "database",
        "db",
        "datastore",
        "data store",
        "storage",
        "store",
    }
    if prop == "technology":
        allowed_attributes |= {"technology", "tech", "platform", "stack"}

    relevant = [
        m for m in memories
        if _memory_attribute(m) in allowed_attributes
        and not _is_vague_value((m.get("content") or {}).get("value"))
    ]
    active = [m for m in relevant if m.get("status") == "ACTIVE"]
    uncertain = [m for m in relevant if m.get("status") == "UNCERTAIN"]

    if not active:
        if uncertain:
            return EvidenceJudgment(
                verdict="UNCERTAIN",
                reason="Only uncertain evidence was found for the requested property.",
            )
        return EvidenceJudgment(
            verdict="UNSUPPORTED",
            reason="No active memory directly establishes the requested property.",
        )

    # Prefer the highest-ranked active memory. Retrieval already ranks by
    # entity/property/value relevance, so this avoids mixing unrelated active
    # memories for the same entity.
    best = active[0]
    best_value = str((best.get("content") or {}).get("value") or "").strip()
    best_norm = "postgresql" if best_value.lower() == "postgres" else best_value.lower()

    if requested:
        requested_norm = "postgresql" if requested == "postgres" else requested
        if best_norm == requested_norm:
            return EvidenceJudgment(
                verdict="SUPPORTED",
                reason="The highest-ranked active memory explicitly establishes the requested value.",
            )
        if best_value:
            return EvidenceJudgment(
                verdict="CONTRADICTED",
                reason=f"The current active memory establishes {best_value} instead.",
            )

    return EvidenceJudgment(
        verdict="SUPPORTED",
        reason="The highest-ranked active memory directly establishes the requested property.",
    )


def judge_evidence(
    question: str,
    memories: list[dict[str, Any]],
) -> tuple[EvidenceJudgment, dict[str, Any]]:
    evidence = _memory_evidence(memories)

    deterministic = _deterministic_property_judge(question, evidence)
    if deterministic is not None:
        return deterministic, {
            "provider": "deterministic",
            "model": None,
        }

    if not os.getenv("API_KEY"):
        return _fallback_judge(question, evidence), {
            "provider": "fallback",
            "model": None,
        }

    try:
        return _judge_with_openrouter(question, evidence)
    except Exception as exc:
        return _fallback_judge(question, evidence), {
            "provider": "fallback",
            "model": None,
            "llm_error": str(exc),
        }


def _extract_value(memory: dict[str, Any]) -> str | None:
    value = (memory.get("content") or {}).get("value")
    if value is None or str(value).strip() == "":
        return None
    return str(value)


def _answer(
    question: str,
    judgment: EvidenceJudgment,
    memories: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> tuple[str, str]:
    if judgment.verdict == "UNSUPPORTED" or not memories:
        return "I don't know that from my memory.", "ABSTAIN"

    intents = set(bundle.get("intents", []))
    active = [m for m in memories if m.get("status") == "ACTIVE"]

    # Why/decision questions must quote/return source evidence, never internal
    # resolver metadata. Prefer explicit causal/decision language in transcripts.
    if intents & {"reason", "decision"} and judgment.verdict == "SUPPORTED":
        candidates: list[str] = []
        for memory in memories:
            for source in memory.get("sources") or []:
                text = str(source.get("evidence") or source.get("formatted_text") or "").strip()
                if text:
                    candidates.append(text)
        if candidates:
            if "reason" in intents:
                for text in candidates:
                    if "because" in text.lower() or "reason" in text.lower() or "so that" in text.lower():
                        return text, "ANSWER"
            if "decision" in intents:
                for text in candidates:
                    if any(w in text.lower() for w in ("decided", "agreed", "decision", "settled")):
                        return text, "ANSWER"
            # No explicit source sentence matched the requested intent.
            return candidates[0], "ANSWER"
        return "I don't have enough information in my saved history to answer that.", "ABSTAIN"

    best = active[0] if active else memories[0]
    value = _extract_value(best)
    if _is_vague_value(value):
        return "I don't have enough specific information in my saved history to answer that.", "ABSTAIN"
    subject = best.get("subject") or "That"
    attribute = (best.get("content") or {}).get("attribute")

    if judgment.verdict == "CONTRADICTED" and value:
        return f"No. {subject} currently uses {value}.", "ANSWER"

    if judgment.verdict == "UNCERTAIN" and value:
        return (
            f"I can't confirm that. My memory of {subject} says {value}, "
            "but that information is uncertain.",
            "ANSWER",
        )

    if best["type"] == "FACT" and attribute and value:
        return f"{subject} {attribute} is {value}.", "ANSWER"

    if best["type"] == "PREFERENCE" and value:
        return f"Your preference is {value}.", "ANSWER"

    if best["type"] == "EPISODE" and (best.get("content") or {}).get("summary"):
        return best["content"]["summary"], "ANSWER"

    return "I don't know that from my memory.", "ABSTAIN"


def _save(
    question,
    answer,
    memory_ids,
    source_ids,
    decision,
    verdict,
    reason,
    latency,
    model,
):
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO answer_runs(
                question, answer, memory_ids, source_transcript_ids, decision,
                evidence_verdict, evidence_reason, latency_ms, model
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                question,
                answer,
                json.dumps(memory_ids),
                json.dumps(source_ids),
                decision,
                verdict,
                reason,
                latency,
                json.dumps(model),
            ),
        )
        conn.commit()
        return cur.lastrowid


def ask_hey_kivi(question: str, limit: int = 8) -> dict[str, Any]:
    started = time.perf_counter()

    bundle = retrieve_evidence_bundle(
        question,
        limit=limit,
    )
    context = bundle["evidence"]

    judgment, model = judge_evidence(
        question,
        context,
    )

    answer, decision = _answer(
        question,
        judgment,
        context,
        bundle,
    )

    source_ids: set[int] = set()
    provenance: list[dict[str, Any]] = []
    seen_provenance: set[tuple[int, int]] = set()
    for memory in context:
        for source in memory.get("sources", []):
            source_ids.add(source["transcript_id"])
            key = (memory["id"], source["transcript_id"])
            if key not in seen_provenance:
                seen_provenance.add(key)
                provenance.append({
                    "memory_id": memory["id"],
                    "transcript_id": source["transcript_id"],
                    "timestamp": source.get("timestamp"),
                    "evidence": source.get("evidence"),
                    "formatted_text": source.get("formatted_text"),
                })

        for event in memory.get("history", []):
            source_id = event.get("source_transcript_id")
            if source_id is not None:
                source_ids.add(source_id)

    memory_ids = [m["id"] for m in context]
    latency = (time.perf_counter() - started) * 1000

    run_id = _save(
        question,
        answer,
        memory_ids,
        sorted(source_ids),
        decision,
        judgment.verdict,
        judgment.reason,
        latency,
        model,
    )

    return {
        "run_id": run_id,
        "question": question,
        "answer": answer,
        "decision": decision,
        "evidence_verdict": judgment.verdict,
        "evidence_reason": judgment.reason,
        "query_context": {
            "entities": bundle["entities"],
            "user_query": bundle["user_query"],
            "attribute_hint": bundle["attribute_hint"],
            "requested_values": bundle["requested_values"],
            "intents": bundle["intents"],
        },
        "memories": context,
        "memory_ids": memory_ids,
        "source_transcript_ids": sorted(source_ids),
        "provenance": provenance,
        "latency_ms": round(latency, 2),
        "model": model,
    }
