from __future__ import annotations

import json
import re
from typing import Any

from app.db.database import get_connection
from app.memory.models import MemoryCandidate, MemoryDecision


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _subject_key(value: str | None) -> str:
    value = _norm(value)
    return re.sub(r"^project\s+", "", value)



ATTRIBUTE_CANONICAL = {
    "db": "database",
    "datastore": "database",
    "data store": "database",
    "storage": "database",
    "store": "database",
    "database": "database",
    "tech": "technology",
    "stack": "technology",
    "platform": "technology",
    "infrastructure": "technology",
    "technology": "technology",
}

VAGUE_VALUES = {
    "existing database setup",
    "current database setup",
    "existing setup",
    "current setup",
    "the existing database",
    "the current database",
    "same setup",
    "existing datastore",
}


def _canonical_attribute(value: str | None) -> str | None:
    key = _norm(value)
    return ATTRIBUTE_CANONICAL.get(key, key or None)


def _is_vague_semantic_value(candidate: MemoryCandidate) -> bool:
    if candidate.type != "FACT":
        return False
    attribute = _canonical_attribute(candidate.attribute)
    value = _norm(candidate.value)
    return attribute in {"database", "technology"} and value in VAGUE_VALUES


def _normalized_candidate(candidate: MemoryCandidate) -> MemoryCandidate:
    if candidate.type not in ("FACT", "PREFERENCE") or not candidate.attribute:
        return candidate
    canonical = _canonical_attribute(candidate.attribute)
    if canonical == candidate.attribute:
        return candidate
    return candidate.model_copy(update={"attribute": canonical})

def _candidate_content(candidate: MemoryCandidate) -> dict[str, Any]:
    if candidate.type in ("FACT", "PREFERENCE"):
        return {
            "attribute": candidate.attribute,
            "value": candidate.value,
        }
    return {
        "summary": candidate.summary,
    }


def _confidence(candidate: MemoryCandidate) -> float:
    return {
        "explicit": 0.96,
        "inferred": 0.65,
        "uncertain": 0.35,
    }[candidate.certainty]


def _same_content(existing: dict[str, Any], candidate: MemoryCandidate) -> bool:
    if candidate.type in ("FACT", "PREFERENCE"):
        return _norm(existing.get("attribute")) == _norm(candidate.attribute) and (
            _norm(str(existing.get("value"))) == _norm(candidate.value)
        )
    return _norm(existing.get("summary")) == _norm(candidate.summary)


def _find_conflicts(conn, candidate: MemoryCandidate):
    if candidate.type in ("FACT", "PREFERENCE"):
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE type = ?
              AND status IN ('ACTIVE', 'UNCERTAIN')
              AND lower(trim(replace(subject, 'Project ', ''))) = lower(trim(replace(?, 'Project ', '')))
            ORDER BY updated_at DESC
            """,
            (candidate.type, candidate.subject),
        ).fetchall()
        canonical = _canonical_attribute(candidate.attribute)
        return [
            row for row in rows
            if _canonical_attribute(json.loads(row["content"]).get("attribute")) == canonical
        ]

    return []


def _log_decision(
    conn,
    transcript_id: int,
    candidate: MemoryCandidate,
    decision: MemoryDecision,
):
    conn.execute(
        """
        INSERT INTO memory_decisions(
            transcript_id, decision, candidate, reason, resulting_memory_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            transcript_id,
            decision.decision,
            candidate.model_dump_json(),
            decision.reason,
            decision.memory_id,
        ),
    )


def resolve_candidate(
    transcript_id: int,
    candidate: MemoryCandidate,
) -> MemoryDecision:
    with get_connection() as conn:
        candidate = _normalized_candidate(candidate)

        if not candidate.should_remember:
            decision = MemoryDecision(
                decision="REJECT",
                reason=candidate.reason,
            )
            _log_decision(conn, transcript_id, candidate, decision)
            conn.commit()
            return decision

        if not candidate.type or not candidate.title or not candidate.subject:
            decision = MemoryDecision(
                decision="REJECT",
                reason="Candidate failed required-field validation.",
            )
            _log_decision(conn, transcript_id, candidate, decision)
            conn.commit()
            return decision

        if candidate.type in ("FACT", "PREFERENCE") and (
            not candidate.attribute or candidate.value is None
        ):
            decision = MemoryDecision(
                decision="REJECT",
                reason="FACT/PREFERENCE requires an attribute and value.",
            )
            _log_decision(conn, transcript_id, candidate, decision)
            conn.commit()
            return decision

        if candidate.type == "EPISODE" and not candidate.summary:
            decision = MemoryDecision(
                decision="REJECT",
                reason="EPISODE requires a summary.",
            )
            _log_decision(conn, transcript_id, candidate, decision)
            conn.commit()
            return decision

        # Do not turn vague placeholders into durable semantic facts. The
        # transcript can still remain in the source corpus, but it should not
        # create an authoritative database/technology memory.
        if _is_vague_semantic_value(candidate):
            decision = MemoryDecision(
                decision="REJECT",
                reason="Rejected vague semantic value; no concrete database/technology was established.",
            )
            _log_decision(conn, transcript_id, candidate, decision)
            conn.commit()
            return decision

        conflicts = _find_conflicts(conn, candidate)

        # Same state already exists: retain it and add provenance.
        for row in conflicts:
            existing_content = json.loads(row["content"])
            if _same_content(existing_content, candidate):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_sources(memory_id, transcript_id, evidence)
                    VALUES (?, ?, ?)
                    """,
                    (row["id"], transcript_id, candidate.evidence),
                )
                conn.execute(
                    """
                    INSERT INTO memory_history(
                        memory_id, event_type, old_value, new_value, reason,
                        source_transcript_id
                    )
                    VALUES (?, 'REINFORCED', ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        json.dumps(existing_content),
                        json.dumps(existing_content),
                        "New transcript independently supports the existing memory.",
                        transcript_id,
                    ),
                )
                decision = MemoryDecision(
                    decision="RETAIN",
                    reason="Equivalent active memory already exists; added provenance.",
                    memory_id=row["id"],
                )
                _log_decision(conn, transcript_id, candidate, decision)
                conn.commit()
                return decision

        # Explicit replacement supersedes the previous state. An uncertain candidate
        # is retained separately and does not erase known current state.
        if conflicts and candidate.certainty == "explicit":
            old = conflicts[0]
            old_content = json.loads(old["content"])
            new_content = _candidate_content(candidate)

            conn.execute(
                """
                UPDATE memories
                SET status = 'SUPERSEDED', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (old["id"],),
            )
            conn.execute(
                """
                INSERT INTO memory_history(
                    memory_id, event_type, old_value, new_value, reason,
                    source_transcript_id
                )
                VALUES (?, 'SUPERSEDED', ?, ?, ?, ?)
                """,
                (
                    old["id"],
                    json.dumps(old_content),
                    json.dumps(new_content),
                    "An explicit later transcript establishes a conflicting value.",
                    transcript_id,
                ),
            )

            cursor = conn.execute(
                """
                INSERT INTO memories(type, title, subject, content, status, confidence)
                VALUES (?, ?, ?, ?, 'ACTIVE', ?)
                """,
                (
                    candidate.type,
                    candidate.title,
                    candidate.subject,
                    json.dumps(new_content),
                    _confidence(candidate),
                ),
            )
            new_id = cursor.lastrowid

            conn.execute(
                """
                INSERT INTO memory_sources(memory_id, transcript_id, evidence)
                VALUES (?, ?, ?)
                """,
                (new_id, transcript_id, candidate.evidence),
            )
            conn.execute(
                """
                INSERT INTO memory_history(
                    memory_id, event_type, old_value, new_value, reason,
                    source_transcript_id
                )
                VALUES (?, 'CREATED', NULL, ?, ?, ?)
                """,
                (
                    new_id,
                    json.dumps(new_content),
                    "Created as the new active value after superseding a conflicting memory.",
                    transcript_id,
                ),
            )

            decision = MemoryDecision(
                decision="UPDATE",
                reason="Explicit later information superseded the previous active value.",
                memory_id=new_id,
                superseded_memory_id=old["id"],
            )
            _log_decision(conn, transcript_id, candidate, decision)
            conn.commit()
            return decision

        # Uncertain conflict: preserve the known active state and store the candidate
        # as UNCERTAIN so it can be surfaced/inspected without silently rewriting truth.
        status = "UNCERTAIN" if conflicts or candidate.certainty == "uncertain" else "ACTIVE"
        new_content = _candidate_content(candidate)

        cursor = conn.execute(
            """
            INSERT INTO memories(type, title, subject, content, status, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.type,
                candidate.title,
                candidate.subject,
                json.dumps(new_content),
                status,
                _confidence(candidate),
            ),
        )
        new_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO memory_sources(memory_id, transcript_id, evidence)
            VALUES (?, ?, ?)
            """,
            (new_id, transcript_id, candidate.evidence),
        )
        conn.execute(
            """
            INSERT INTO memory_history(
                memory_id, event_type, old_value, new_value, reason,
                source_transcript_id
            )
            VALUES (?, 'CREATED', NULL, ?, ?, ?)
            """,
            (
                new_id,
                json.dumps(new_content),
                "Created from transcript after candidate validation.",
                transcript_id,
            ),
        )

        decision = MemoryDecision(
            decision="UNCERTAIN" if status == "UNCERTAIN" else "CREATE",
            reason=(
                "Conflicting candidate retained as UNCERTAIN; existing active state was preserved."
                if status == "UNCERTAIN"
                else "Candidate passed validation and was persisted as active memory."
            ),
            memory_id=new_id,
        )
        _log_decision(conn, transcript_id, candidate, decision)
        conn.commit()
        return decision
