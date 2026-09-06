# Kivi — Semantic Memory for Dictation

Kivi turns scattered dictation history into a selective, evolving semantic memory layer for Hey Kivi.

The system remembers durable **facts**, **preferences**, and meaningful **episodes**; deliberately ignores transient or unsupported information; evolves memories when the user's context changes; and exposes the evidence behind answers.

## Product

Kivi is designed for knowledge workers who dictate throughout the day and later remember telling Kivi something without wanting to search their transcript history manually.

The core promise is:

> You speak → Kivi understands what remains useful → Kivi uses that understanding later.

The product deliberately distinguishes regular dictation from Hey Kivi. Dictation captures speech; Hey Kivi uses accumulated semantic context.

## Core behaviours

- **Selective memory:** durable, useful, supported information is remembered; filler and weak inference are ignored.
- **Memory evolution:** later explicit facts supersede older facts while preserving lineage.
- **Uncertainty:** tentative future changes remain uncertain instead of becoming current truth.
- **Grounded answers:** Hey Kivi answers from stored memories and source evidence.
- **Abstention:** if history does not support an answer, Kivi says it does not know.
- **Provenance:** answers and memories can be traced to source transcripts and memory history.
- **User control:** memories can be inspected and deleted through the UI.

## Architecture

```text
Web UI
  │
  ▼
FastAPI
  ├── Memory extraction
  ├── Memory resolution
  ├── Retrieval
  └── Hey Kivi evidence judging
  │
  ▼
SQLite
  ├── transcripts
  ├── memories
  ├── memory_sources
  ├── memory_history
  ├── memory_decisions
  └── answer_runs
```

The LLM proposes structured memory candidates and helps judge answer evidence. Backend validation and resolution remain authoritative for database state.

Retrieval uses structured lookup / SQLite text search rather than requiring a vector database.

## Repository contents

- `app/` — FastAPI backend and memory pipeline
- `web/` — normal-user web interface
- `database/schema.sql` — SQLite schema
- `corpus/` — development corpus and expected behaviour
- `scripts/import_corpus.py` — corpus importer
- `scripts/evaluate_corpus.py` — reproducible evaluation
- `scripts/reset_db.py` — reset local state
- `scripts/init_db.py` — initialize schema
- `positioning.md` — product positioning
- `vision.md` — product vision
- `RUN.md` — exact review procedure

## Limitations

This is a focused semantic-memory prototype. It does not implement speech recognition or production Kivi integration. Transcripts can be replayed through the documented HTTP/API or UI workflow. The assignment explicitly permits this approach.

The evaluation model is probabilistic, so latency and model responses can vary. The evaluation records the actual decision, reason, model and latency rather than hiding failures.

## Evaluation

The included evaluation runs the complete transcript → extraction → resolution pipeline through the HTTP API and records:

- processing success/errors
- memory decisions
- latency
- memory state and types
- duplicate/conflicting identities
- provenance coverage
- history events
- model/fallback usage
- expected-decision comparison

Expected labels are an evaluation aid, not a substitute for semantic review.
