"""Targeted repair for vague active semantic facts.

This script preserves the existing SQLite database and history. It only repairs
an ACTIVE FACT whose database/technology value is a known vague placeholder,
when there is a concrete superseded predecessor for the same semantic identity.

It is intentionally conservative: ambiguous cases are reported, not changed.
"""
from __future__ import annotations

import json
import re
from app.db.database import get_connection

VAGUE = {
    "existing database setup",
    "current database setup",
    "existing setup",
    "current setup",
    "the existing database",
    "the current database",
    "same setup",
    "existing datastore",
}
DB_ATTRS = {"database", "db", "datastore", "data store", "storage", "store"}

def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def subject_key(s):
    return re.sub(r"^project\s+", "", norm(s))

def attr_key(s):
    k = norm(s)
    return "database" if k in DB_ATTRS else k

def content(row):
    try:
        return json.loads(row["content"])
    except Exception:
        return {}

def is_vague(row):
    c = content(row)
    return row["type"] == "FACT" and attr_key(c.get("attribute")) == "database" and norm(c.get("value")) in VAGUE

def is_concrete(row):
    c = content(row)
    return row["type"] == "FACT" and attr_key(c.get("attribute")) == "database" and norm(c.get("value")) not in VAGUE and bool(norm(c.get("value")))

def main():
    with get_connection() as conn:
        active = conn.execute(
            "SELECT * FROM memories WHERE status='ACTIVE' AND type='FACT' ORDER BY id"
        ).fetchall()
        repairs = []
        ambiguous = []

        for bad in active:
            if not is_vague(bad):
                continue
            c = content(bad)
            candidates = conn.execute(
                """
                SELECT * FROM memories
                WHERE type='FACT'
                  AND status='SUPERSEDED'
                  AND lower(trim(replace(subject,'Project ',''))) = lower(trim(replace(?, 'Project ','')))
                ORDER BY updated_at DESC, id DESC
                """,
                (bad["subject"],),
            ).fetchall()
            concrete = [r for r in candidates if is_concrete(r)]
            # Prefer predecessors that have a direct SUPERSEDED history event
            # whose new value matches this bad memory.
            direct = []
            for r in concrete:
                hist = conn.execute(
                    """
                    SELECT 1 FROM memory_history
                    WHERE memory_id=? AND event_type='SUPERSEDED'
                      AND new_value LIKE ?
                    LIMIT 1
                    """,
                    (r["id"], f"%{c.get('value')}%"),
                ).fetchone()
                if hist:
                    direct.append(r)
            candidates = direct or concrete

            # Only repair when there is exactly one plausible concrete predecessor.
            if len(candidates) != 1:
                ambiguous.append((bad["id"], bad["subject"], [r["id"] for r in candidates]))
                continue

            old = candidates[0]
            old_content = content(old)
            bad_content = content(bad)
            conn.execute(
                "UPDATE memories SET status='SUPERSEDED', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (bad["id"],),
            )
            conn.execute(
                "UPDATE memories SET status='ACTIVE', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (old["id"],),
            )
            reason = (
                "Repaired invalid semantic state: a vague database value was active "
                "and had superseded a concrete database memory. Restored the concrete predecessor."
            )
            conn.execute(
                """
                INSERT INTO memory_history(
                    memory_id,event_type,old_value,new_value,reason,source_transcript_id
                ) VALUES(?,?,?,?,?,NULL)
                """,
                (bad["id"], "REPAIRED", json.dumps(bad_content), json.dumps(bad_content), reason),
            )
            conn.execute(
                """
                INSERT INTO memory_history(
                    memory_id,event_type,old_value,new_value,reason,source_transcript_id
                ) VALUES(?,?,?,?,?,NULL)
                """,
                (old["id"], "REPAIRED", json.dumps(old_content), json.dumps(old_content), reason),
            )
            repairs.append((bad["id"], old["id"], old_content.get("value")))

        conn.commit()

    print("Semantic state repair")
    print("=" * 60)
    if repairs:
        for bad_id, old_id, value in repairs:
            print(f"REPAIRED: vague active #{bad_id} -> concrete active #{old_id} ({value})")
    else:
        print("No automatic repairs made.")
    if ambiguous:
        print("\nAMBIGUOUS / NOT CHANGED:")
        for item in ambiguous:
            print(f"  active #{item[0]} ({item[1]}), candidate predecessors={item[2]}")
    print(f"\nRepairs: {len(repairs)}")

if __name__ == "__main__":
    main()
