from __future__ import annotations

import json

from app.db.database import get_connection


def memory_trace(memory_id: int) -> dict:
    with get_connection() as conn:
        memory = conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if memory is None:
            return {}

        sources = conn.execute(
            """
            SELECT ms.id, ms.evidence, ms.created_at,
                   t.id AS transcript_id, t.timestamp,
                   t.raw_asr, t.formatted_text
            FROM memory_sources ms
            JOIN transcripts t ON t.id = ms.transcript_id
            WHERE ms.memory_id = ?
            ORDER BY t.timestamp
            """,
            (memory_id,),
        ).fetchall()

        history = conn.execute(
            """
            SELECT * FROM memory_history
            WHERE memory_id = ?
            ORDER BY created_at
            """,
            (memory_id,),
        ).fetchall()

        result = dict(memory)
        result["content"] = json.loads(result["content"])
        result["sources"] = [dict(row) for row in sources]
        result["history"] = [dict(row) for row in history]
        return result
