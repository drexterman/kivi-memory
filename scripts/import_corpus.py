#!/usr/bin/env python3
"""Import and process a JSONL transcript corpus through the running Kivi API.

Usage:
    python scripts/import_corpus.py --file corpus/dev_30.jsonl
    python scripts/import_corpus.py --file corpus/dev_30.jsonl --base-url http://127.0.0.1:8000
    python scripts/import_corpus.py --file corpus/dev_30.jsonl --no-process
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_json(base_url: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to Kivi at {base_url}. Is the server running?"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to a JSONL corpus")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--no-process",
        action="store_true",
        help="Import transcripts but do not run memory extraction/resolution",
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"Corpus file not found: {path}", file=sys.stderr)
        return 1

    imported = 0
    processed = 0

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON on line {line_no}: {exc}", file=sys.stderr)
            return 1

        payload = {
            "timestamp": record["timestamp"],
            "raw_asr": record["raw_asr"],
            "formatted_text": record["formatted_text"],
            "metadata": {
                **record.get("metadata", {}),
                "corpus_record_id": record.get("id"),
            },
        }

        transcript = post_json(args.base_url, "/api/transcripts", payload)
        imported += 1

        if not args.no_process:
            result = post_json(
                args.base_url,
                f"/api/transcripts/{transcript['id']}/process-memory",
                {},
            )
            decision = result["decision"]["decision"]
            processed += 1
            print(
                f"{record.get('id', line_no):>8}  "
                f"transcript={transcript['id']:>3}  "
                f"decision={decision:<9}"
            )
        else:
            print(
                f"{record.get('id', line_no):>8}  "
                f"transcript={transcript['id']:>3}  imported"
            )

    print(f"\nImported: {imported}")
    if not args.no_process:
        print(f"Processed: {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
