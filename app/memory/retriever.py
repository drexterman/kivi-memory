from __future__ import annotations

import json
import re
from typing import Any

from app.db.database import get_connection


STOPWORDS = {
    "what", "which", "who", "when", "where", "why", "how", "does", "did",
    "do", "is", "are", "was", "were", "am", "i", "my", "me", "we", "our",
    "the", "a", "an", "for", "of", "to", "in", "on", "about", "with", "and",
    "or", "this", "that", "it", "use", "using", "used", "currently", "current",
    "now", "tell", "know", "can", "you", "please", "have", "has", "had", "from",
    "its", "their", "there", "they", "be", "been", "being", "doesn", "not", "yet",
}

KNOWN_ENTITIES = {
    "atlas", "apollo", "beacon", "lyra", "polaris", "artemis", "comet", "echo",
    "pulse", "nova", "orion", "helios", "luna",
}

ATTRIBUTE_GROUPS = {
    "database": {
        "database", "db", "datastore", "data store", "storage", "store",
    },
    "technology": {
        "technology", "tech", "stack", "platform", "infrastructure", "setup",
    },
    "deployment": {
        "deployment", "deployed", "running", "run", "execution", "environment",
    },
    "release": {
        "release", "cadence", "cycle", "train",
    },
    "capability": {
        "capability", "capabilities", "supports", "support", "able",
    },
    "format": {
        "format", "style", "report format", "output format",
    },
}

ATTRIBUTE_EQUIVALENTS = {
    "database": {"database", "db", "datastore", "data store", "storage", "store"},
    "technology": {
        "technology", "tech", "stack", "platform", "infrastructure", "setup", "database"
    },
    "deployment": {"deployment", "deployed", "running", "execution", "environment"},
    "release": {"release", "cadence", "cycle", "train", "release train"},
    "format": {"format", "style", "report format", "output format"},
}

INTENT_WORDS = {
    "reason": {"why", "reason", "because", "chose", "choose", "chosen"},
    "decision": {"decide", "decision", "decided", "agreed", "agreement", "settled"},
    "person": {"ceo", "cto", "owner", "manager", "lead", "founder", "name"},
    "preference": {"preference", "prefer", "preferred", "like", "want"},
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


def _is_vague_value(value: str | None) -> bool:
    return _norm(value) in VAGUE_VALUES


VALUE_ALIASES = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "duckdb": "duckdb",
    "sqlite": "sqlite",
    "redis": "redis",
    "kafka": "kafka",
    "valkey": "valkey",
    "mysql": "mysql",
    "mongodb": "mongodb",
    "mongo": "mongodb",
}


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9][a-z0-9_-]*", _norm(text))
    return [t for t in raw if len(t) > 2 and t not in STOPWORDS]


def _canonical_subject(text: str | None) -> str:
    value = _norm(text)
    value = re.sub(r"^project\s+", "", value)
    return value


def _subject_forms(query: str) -> set[str]:
    q = _norm(query)
    entities: set[str] = set()

    for entity in KNOWN_ENTITIES:
        if re.search(rf"\b(?:project\s+)?{re.escape(entity)}\b", q):
            entities.add(entity)

    # Also recognize "Project Foo" for entities outside the development corpus.
    for match in re.findall(r"\bproject\s+([a-z][a-z0-9_-]*)\b", q):
        entities.add(_canonical_subject(match))

    return entities


def _is_user_query(query: str) -> bool:
    q = _norm(query)
    return bool(re.search(r"\b(my|me|i)\b", q)) and not _subject_forms(q)


def _attribute_hint(query: str) -> str | None:
    q = _norm(query)
    phrases: list[tuple[int, str, str]] = []
    for canonical, words in ATTRIBUTE_GROUPS.items():
        for word in words:
            phrases.append((len(word), canonical, word))
    phrases.sort(reverse=True)

    for _, canonical, phrase in phrases:
        if re.search(rf"\b{re.escape(phrase)}\b", q):
            return canonical
    return None


def _intent_hints(query: str) -> set[str]:
    q = _norm(query)
    result: set[str] = set()
    for intent, words in INTENT_WORDS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", q) for word in words):
            result.add(intent)
    return result



def _question_property(query: str, intents: set[str], attribute_hint: str | None) -> str | None:
    if attribute_hint:
        return attribute_hint
    q = _norm(query)
    if "database" in q or "data store" in q or "datastore" in q:
        return "database"
    if any(x in q for x in ("technology", "tech", "stack", "platform")):
        return "technology"
    if any(x in q for x in ("deployment", "deployed", "running on", "run on")):
        return "deployment"
    if any(x in q for x in ("report format", "format", "style")) and "preference" in intents:
        return "format"
    if "ceo" in q:
        return "person"
    return None

def _requested_values(query: str) -> set[str]:
    q = _norm(query)
    values: set[str] = set()
    for raw, canonical in VALUE_ALIASES.items():
        if re.search(rf"\b{re.escape(raw)}\b", q):
            values.add(canonical)
    return values


def _load_memory(row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["content"] = json.loads(item["content"])
    except (TypeError, json.JSONDecodeError):
        item["content"] = {}
    return item


def _memory_attribute(memory: dict[str, Any]) -> str:
    return _norm(str((memory.get("content") or {}).get("attribute", "")))


def _memory_value(memory: dict[str, Any]) -> str:
    return _norm(str((memory.get("content") or {}).get("value", "")))


def _memory_text(memory: dict[str, Any]) -> str:
    content = memory.get("content") or {}
    return " ".join(
        _norm(str(x))
        for x in (
            memory.get("title"), memory.get("subject"),
            content.get("attribute"), content.get("value"), content.get("summary"),
        )
        if x is not None
    )


def _entity_matches(memory: dict[str, Any], entities: set[str], user_query: bool) -> bool:
    if user_query:
        return _canonical_subject(memory.get("subject")) in {"user", "me", "myself"}
    if not entities:
        return True

    subject = _canonical_subject(memory.get("subject"))
    title = _canonical_subject(memory.get("title"))

    for entity in entities:
        if subject == entity or title == entity or title.startswith(entity + " "):
            return True
    return False


def _attribute_relation(attribute: str, hint: str | None) -> str:
    if not hint or not attribute:
        return "none"
    if attribute == hint:
        return "exact"
    if attribute in ATTRIBUTE_EQUIVALENTS.get(hint, set()):
        return "semantic"
    return "none"


def _score_memory(
    memory: dict[str, Any],
    query_tokens: list[str],
    entities: set[str],
    user_query: bool,
    attribute_hint: str | None,
    intents: set[str],
    requested_values: set[str],
) -> tuple[float, dict[str, Any]] | None:
    if not _entity_matches(memory, entities, user_query):
        return None

    attribute = _memory_attribute(memory)
    value = _memory_value(memory)
    title = _norm(memory.get("title"))
    subject = _norm(memory.get("subject"))
    summary = _norm(str((memory.get("content") or {}).get("summary", "")))
    relation = _attribute_relation(attribute, attribute_hint)

    score = 0.0

    if entities or user_query:
        score += 60.0

    if relation == "exact":
        score += 45.0
    elif relation == "semantic":
        score += 24.0

    # Concrete values are substantially more useful than vague placeholders.
    # Vague database/setup values are retained for auditability but should not
    # outrank an explicit technology value when answering a property question.
    if attribute_hint in {"database", "technology"}:
        if _is_vague_value(value):
            score -= 70.0
        elif value:
            score += 12.0

    # A value explicitly named in the question is highly informative.
    value_match = False
    for requested in requested_values:
        if VALUE_ALIASES.get(value, value) == requested or requested in value:
            value_match = True
            score += 35.0
            break

    # General lexical overlap, deliberately weaker than entity/property/value.
    for token in query_tokens:
        if token in title:
            score += 3.0
        if token in subject:
            score += 2.0
        if token in attribute:
            score += 2.0
        if token in value:
            score += 2.0
        if token in summary:
            score += 1.0

    if "reason" in intents:
        reason_text = title + " " + summary
        if any(word in reason_text for word in ("because", "reason", "why", "choice", "chose")):
            score += 26.0
        if memory.get("type") == "EPISODE":
            score += 18.0
        if memory.get("sources") or memory.get("history"):
            score += 8.0

    if "decision" in intents:
        decision_text = title + " " + summary
        if any(word in decision_text for word in ("decision", "decided", "agreed", "agreement", "settled", "outcome")):
            score += 28.0
        if memory.get("type") == "EPISODE":
            score += 24.0
        # Decision questions should favor memories with actual source/history evidence.
        if memory.get("sources") or memory.get("history"):
            score += 8.0

    if "preference" in intents and memory.get("type") == "PREFERENCE":
        score += 20.0

    if "person" in intents and attribute in {"ceo", "cto", "owner", "manager", "lead", "founder", "name"}:
        score += 30.0

    status = memory.get("status")
    if status == "ACTIVE":
        score += 8.0
    elif status == "UNCERTAIN":
        score += 2.0
    elif status == "SUPERSEDED":
        score -= 10.0

    try:
        score += min(max(float(memory.get("confidence") or 0.0), 0.0), 1.0)
    except (TypeError, ValueError):
        pass

    debug = {
        "entities": sorted(entities),
        "user_query": user_query,
        "attribute_hint": attribute_hint,
        "attribute_relation": relation,
        "requested_values": sorted(requested_values),
        "value_match": value_match,
        "intents": sorted(intents),
    }
    return score, debug


def _query_context(query: str) -> dict[str, Any]:
    return {
        "tokens": _tokens(query),
        "entities": _subject_forms(query),
        "user_query": _is_user_query(query),
        "attribute_hint": _attribute_hint(query),
        "intents": _intent_hints(query),
        "requested_values": _requested_values(query),
    }


def _fetch_memories(statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    placeholders = ", ".join("?" for _ in statuses)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, type, title, subject, content, status, confidence,
                   created_at, updated_at
            FROM memories
            WHERE status IN ({placeholders})
            """,
            statuses,
        ).fetchall()
    return [_load_memory(row) for row in rows]


def _rank(query: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ctx = _query_context(query)
    ranked: list[dict[str, Any]] = []

    for memory in memories:
        result = _score_memory(
            memory,
            ctx["tokens"],
            ctx["entities"],
            ctx["user_query"],
            ctx["attribute_hint"],
            ctx["intents"],
            ctx["requested_values"],
        )
        if result is None:
            continue

        score, debug = result
        if score <= 0:
            continue

        memory["retrieval_score"] = round(score, 4)
        memory["retrieval_debug"] = debug
        ranked.append(memory)

    ranked.sort(
        key=lambda x: (
            -x["retrieval_score"],
            -(float(x.get("confidence") or 0.0)),
            x.get("id", 0),
        )
    )
    return ranked


def _attach_history_and_sources(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not memories:
        return []

    ids = [m["id"] for m in memories]
    placeholders = ", ".join("?" for _ in ids)

    with get_connection() as conn:
        source_rows = conn.execute(
            f"""
            SELECT ms.memory_id, ms.transcript_id, ms.evidence,
                   t.timestamp, t.raw_asr, t.formatted_text
            FROM memory_sources ms
            JOIN transcripts t ON t.id = ms.transcript_id
            WHERE ms.memory_id IN ({placeholders})
            ORDER BY t.timestamp
            """,
            ids,
        ).fetchall()

        history_rows = conn.execute(
            f"""
            SELECT memory_id, event_type, old_value, new_value,
                   reason, source_transcript_id, created_at
            FROM memory_history
            WHERE memory_id IN ({placeholders})
            ORDER BY created_at
            """,
            ids,
        ).fetchall()

    sources_by_memory: dict[int, list[dict[str, Any]]] = {}
    history_by_memory: dict[int, list[dict[str, Any]]] = {}

    for row in source_rows:
        item = dict(row)
        sources_by_memory.setdefault(item["memory_id"], []).append(item)

    for row in history_rows:
        item = dict(row)
        history_by_memory.setdefault(item["memory_id"], []).append(item)

    for memory in memories:
        memory["sources"] = sources_by_memory.get(memory["id"], [])
        memory["history"] = history_by_memory.get(memory["id"], [])

    return memories



def _intent_filter(ranked: list[dict[str, Any]], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    if not ranked:
        return ranked

    intents = ctx["intents"]
    # Decision questions: if actual episodes/decision-like memories exist, prefer them.
    if "decision" in intents:
        preferred = [
            m for m in ranked
            if m.get("type") == "EPISODE"
            or any(w in _norm(str(m.get("title"))) + " " + _norm(str((m.get("content") or {}).get("summary", "")))
                   for w in ("decision", "decided", "agreed", "outcome", "settled"))
        ]
        if preferred:
            return preferred

    # Person questions: don't pad with arbitrary project facts.
    if "person" in intents:
        preferred = [
            m for m in ranked
            if _memory_attribute(m) in {"ceo", "cto", "owner", "manager", "lead", "founder", "name"}
        ]
        if preferred:
            return preferred
        return []

    # Preference questions: restrict to preferences whenever available.
    if "preference" in intents:
        preferred = [m for m in ranked if m.get("type") == "PREFERENCE"]
        if preferred:
            return preferred

    return ranked

def retrieve_memories(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Retrieve current ACTIVE memories with entity/property/value-aware ranking."""
    query = str(query or "").strip()
    if not query or not _tokens(query):
        return []

    ranked = _rank(query, _fetch_memories(("ACTIVE",)))

    # If an explicit property was requested and exact property memories exist,
    # don't pad the result with unrelated properties.
    ctx = _query_context(query)
    if ctx["attribute_hint"]:
        exact = [
            m for m in ranked
            if m["retrieval_debug"]["attribute_relation"] == "exact"
            and not (
                ctx["attribute_hint"] in {"database", "technology"}
                and _is_vague_value(_memory_value(m))
            )
        ]
        if exact:
            ranked = exact

    ranked = _intent_filter(ranked, ctx)
    return ranked[: max(1, min(limit, 50))]


def retrieve_related_memories(query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Retrieve active, uncertain, and superseded memories for context/history."""
    query = str(query or "").strip()
    if not query or not _tokens(query):
        return []

    ranked = _rank(
        query,
        _fetch_memories(("ACTIVE", "UNCERTAIN", "SUPERSEDED")),
    )

    ctx = _query_context(query)
    if ctx["attribute_hint"]:
        exact = [
            m for m in ranked
            if m["retrieval_debug"]["attribute_relation"] == "exact"
            and not (
                ctx["attribute_hint"] in {"database", "technology"}
                and _is_vague_value(_memory_value(m))
            )
        ]
        if exact:
            ranked = exact

    ranked = _intent_filter(ranked, ctx)
    return _attach_history_and_sources(ranked[: max(1, min(limit, 50))])


def retrieve_evidence_bundle(query: str, limit: int = 8) -> dict[str, Any]:
    """Build the evidence bundle Hey Kivi needs.

    Normal factual questions use active memories. Reason/decision questions also
    pull historical/uncertain memories and their provenance. This keeps retrieval
    deterministic while giving the evidence judge enough context to explain change.
    """
    query = str(query or "").strip()
    ctx = _query_context(query)

    active = retrieve_memories(query, limit=limit)
    related = retrieve_related_memories(query, limit=max(limit * 2, 12))

    # Property questions need historical values when an old active record is
    # semantically vague. Keep concrete historical evidence for the judge.
    if ctx["attribute_hint"] in {"database", "technology"}:
        related = [
            m for m in related
            if (
                m["retrieval_debug"]["attribute_relation"] in {"exact", "semantic"}
                and not _is_vague_value(_memory_value(m))
            )
            or m.get("status") == "ACTIVE"
        ]

    # For reason/decision questions, historical context is first-class evidence.
    needs_history = bool(ctx["intents"] & {"reason", "decision"})

    if needs_history:
        selected = related[: max(limit, 8)]
    else:
        active_ids = {m["id"] for m in active}
        selected = active + [
            m for m in related
            if m["id"] not in active_ids
        ][: max(0, limit - len(active))]

    selected = _attach_history_and_sources(selected)

    return {
        "query": query,
        "entities": sorted(ctx["entities"]),
        "user_query": ctx["user_query"],
        "attribute_hint": ctx["attribute_hint"],
        "requested_values": sorted(ctx["requested_values"]),
        "intents": sorted(ctx["intents"]),
        "active": active,
        "related": related,
        "evidence": selected,
    }
