"""Smoke-test Phase 3 memory lifecycle without an external LLM."""
from app.db.database import get_connection, initialize_database, reset_database
from app.memory.extractor import extract_memory
from app.memory.resolver import resolve_candidate

CASES = [
    ("For Project Atlas we are using PostgreSQL.", "CREATE"),
    ("I switched Project Atlas to DuckDB because I want local execution.", "UPDATE"),
    ("I am thinking about switching Project Atlas to SQLite.", "UNCERTAIN"),
    ("I have been working late this week.", "REJECT"),
    ("For Project Atlas we are still using DuckDB.", "RETAIN"),
]

reset_database()
initialize_database()

for idx, (text, expected) in enumerate(CASES, 1):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO transcripts(timestamp, raw_asr, formatted_text, metadata) VALUES (?, ?, ?, ?)",
            (f"2026-09-05T{10 + idx:02d}:00:00", text, text, "{}"),
        )
        transcript_id = cur.lastrowid
        conn.commit()

    candidate, _ = extract_memory(text)
    decision = resolve_candidate(transcript_id, candidate)
    actual = decision.decision
    print(f"{idx}. {actual:9s} expected={expected:9s} | {text}")
    assert actual == expected, (text, actual, expected)

with get_connection() as conn:
    memories = [dict(r) for r in conn.execute(
        "SELECT id, subject, content, status FROM memories ORDER BY id"
    ).fetchall()]
    sources = conn.execute("SELECT COUNT(*) AS n FROM memory_sources").fetchone()["n"]

assert memories[0]["status"] == "SUPERSEDED"
assert memories[1]["status"] == "ACTIVE"
assert memories[2]["status"] == "UNCERTAIN"
assert sources == 4
print("\nPASS: Phase 3 lifecycle, supersession, uncertainty, rejection, and retention/provenance.")
