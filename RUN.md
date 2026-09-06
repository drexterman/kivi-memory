# Kivi — Review & Run Guide

## Primary review method

**Local application:** FastAPI backend + SQLite database + browser UI.

Primary URL after startup:

```text
http://127.0.0.1:8000
```

No hosted service is required.

## Requirements

- Python 3.11+ recommended
- An OpenRouter-compatible API key for LLM extraction/evidence judging
- Internet access from the Python process for model calls

## 1. Install

From the repository root:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Configure environment

Copy `.env.example` to `.env` and set the key:

```text
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=mistralai/mistral-small-3.2-24b-instruct:free
```

Do not commit the private key.

The variable name is intentionally `OPENAI_API_KEY` because the application uses the OpenAI-compatible client interface against OpenRouter.

## 3. Initialize the database

For a fresh clone:

```bash
python -m scripts.init_db
```

The SQLite database is created under:

```text
data/kivi.sqlite3
```

**Do not run reset/init against an existing evaluation state unless you intentionally want to discard that local state.**

## 4. Start the application

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## 5. Primary product demo

Use **Add context** to create an evolving decision:

1. Add:
   `Atlas uses PostgreSQL.`
2. Add:
   `I've switched Atlas to DuckDB because I need local execution.`
3. Open **Hey Kivi**.
4. Ask:
   `What database does Project Atlas use?`
5. Inspect **Why does Kivi know this?**.
6. Open **Your Memory** and inspect the Atlas memory/history.
7. Ask:
   `Why did I choose DuckDB for Atlas?`
8. Ask an unsupported question such as:
   `What is Apollo's CEO's name?`

Expected behaviour is DuckDB, an evidence-backed causal explanation, and abstention respectively.

## 6. Import a corpus

The importer uses the running HTTP API:

```bash
python scripts/import_corpus.py corpus/dev_30.jsonl
```

For a larger corpus, pass the corresponding JSONL file using the same command format.

The importer creates transcripts and invokes memory processing for each record.

## 7. Run evaluation

With the server running:

```bash
python scripts/evaluate_corpus.py
```

If the script accepts a corpus path in the current checkout, use the documented/default evaluation corpus supplied with the repository.

The evaluation should be run against a fresh database when measuring a complete corpus from scratch. Preserve the resulting report as an artifact of the submitted evaluation run.

## 8. Inspect state

The UI exposes memories and provenance directly.

The API also exposes memory and answer-run state. Useful endpoints include:

```text
GET  /health
GET  /api/memories
GET  /api/memories/{id}
GET  /api/transcripts
POST /api/hey-kivi
GET  /api/answer-runs
```

Evaluation output contains per-record decisions, reasons, candidate/model information and latency.

## 9. Reset

Only when intentionally starting over:

```bash
python -m scripts.reset_db
```

Then initialize again if required:

```bash
python -m scripts.init_db
```

**Never use reset as part of the normal demo workflow.**

## 10. Clean-room release check

Before submitting a commit, verify this complete path:

```text
fresh clone
  ↓
create virtual environment
  ↓
pip install -r requirements.txt
  ↓
configure .env
  ↓
python -m scripts.init_db
  ↓
uvicorn app.main:app --reload
  ↓
open browser
  ↓
run primary demo
  ↓
inspect memory + provenance
  ↓
import corpus
  ↓
run evaluation
  ↓
inspect generated results
  ↓
reset only if needed
```

The evaluator will not be expected to repair undocumented setup problems.
