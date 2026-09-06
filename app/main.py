from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db.database import get_connection, initialize_database, row_to_dict, migrate_phase4_evidence_judge
from app.hey_kivi.service import ask_hey_kivi
from app.memory.extractor import extract_memory
from app.memory.provenance import memory_trace
from app.memory.retriever import retrieve_memories, retrieve_related_memories
from app.memory.resolver import resolve_candidate
from app.schemas import MemoryCreate, TranscriptCreate

app = FastAPI(
    title="Kivi Semantic Memory",
    version="0.2.0",
    description="Backend foundation for Kivi's selective, evolving semantic memory.",
)


app.mount("/static", StaticFiles(directory="web"), name="static")

@app.get("/")
def ui():
    return FileResponse("web/index.html")

@app.on_event("startup")
def startup() -> None:
    initialize_database()
    migrate_phase4_evidence_judge()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/transcripts", status_code=201)
def create_transcript(payload: TranscriptCreate):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO transcripts(timestamp, raw_asr, formatted_text, metadata)
            VALUES (?, ?, ?, ?)
            """,
            (
                payload.timestamp.isoformat(),
                payload.raw_asr,
                payload.formatted_text,
                json.dumps(payload.metadata),
            ),
        )
        row = conn.execute(
            "SELECT * FROM transcripts WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return row_to_dict(row)


@app.get("/api/transcripts")
def list_transcripts(limit: int = 100):
    limit = max(1, min(limit, 500))
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transcripts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [row_to_dict(row) for row in rows]


@app.get("/api/transcripts/search")
def search_transcripts(q: str):
    if not q.strip():
        return []

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.*
            FROM transcripts_fts f
            JOIN transcripts t ON t.id = f.rowid
            WHERE transcripts_fts MATCH ?
            ORDER BY t.timestamp DESC
            LIMIT 50
            """,
            (q,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


@app.get("/api/transcripts/{transcript_id}")
def get_transcript(transcript_id: int):
    with get_connection() as conn:
        result = row_to_dict(
            conn.execute(
                "SELECT * FROM transcripts WHERE id = ?", (transcript_id,)
            ).fetchone()
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Transcript not found")
        return result


@app.post("/api/transcripts/{transcript_id}/process-memory")
def process_transcript_memory(transcript_id: int):
    with get_connection() as conn:
        transcript = conn.execute(
            "SELECT * FROM transcripts WHERE id = ?", (transcript_id,)
        ).fetchone()

    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")

    candidate, model_info = extract_memory(transcript["formatted_text"])
    decision = resolve_candidate(transcript_id, candidate)

    result = {
        "transcript_id": transcript_id,
        "extraction": candidate.model_dump(),
        "decision": decision.model_dump(),
        "model": model_info,
    }

    if decision.memory_id is not None:
        result["memory"] = memory_trace(decision.memory_id)
    else:
        result["memory"] = None

    return result


@app.post("/api/memories", status_code=201)
def create_memory(payload: MemoryCreate):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO memories(type, title, subject, content, status, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.type,
                payload.title,
                payload.subject,
                json.dumps(payload.content),
                payload.status,
                payload.confidence,
            ),
        )
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        result = row_to_dict(row)
        result["content"] = json.loads(result["content"])
        return result


@app.get("/api/memories")
def list_memories(status: str = "ACTIVE", limit: int = 100):
    limit = max(1, min(limit, 500))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE status = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
        results = []
        for row in rows:
            result = row_to_dict(row)
            result["content"] = json.loads(result["content"])
            results.append(result)
        return results


@app.get("/api/memories/{memory_id}")
def get_memory(memory_id: int):
    result = memory_trace(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@app.get("/api/memory-decisions")
def list_memory_decisions(limit: int = 100):
    limit = max(1, min(limit, 500))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memory_decisions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["candidate"] = json.loads(result["candidate"])
            results.append(result)
        return results


@app.get("/api/retrieval")
def inspect_retrieval(q: str, limit: int = 10, include_history: bool = True):
    q = str(q).strip()
    if not q:
        raise HTTPException(status_code=422, detail="q is required")

    limit = max(1, min(limit, 50))

    active = retrieve_memories(q, limit=limit)
    related = (
        retrieve_related_memories(q, limit=limit)
        if include_history
        else []
    )

    return {
        "query": q,
        "active": active,
        "related": related,
    }


@app.post("/api/hey-kivi")
def hey_kivi(payload: dict):
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")
    limit = max(1, min(int(payload.get("limit", 8)), 20))
    return ask_hey_kivi(question, limit=limit)


@app.get("/api/answer-runs")
def list_answer_runs(limit: int = 100):
    limit = max(1, min(limit, 500))
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM answer_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["memory_ids"] = json.loads(item["memory_ids"])
            item["source_transcript_ids"] = json.loads(item["source_transcript_ids"])
            item["model"] = json.loads(item["model"])
            out.append(item)
        return out
