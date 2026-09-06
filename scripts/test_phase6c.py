from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE = os.getenv("KIVI_BASE_URL", "http://127.0.0.1:8000")

CASES = [
    "What database does Project Atlas use?",
    "Is Atlas using PostgreSQL?",
    "What technology is Beacon using?",
    "What does Beacon use for its data store?",
    "What is my preferred report format?",
    "What did we decide about the Atlas project?",
    "What is Apollo's CEO's name?",
    "Why did I choose DuckDB for Atlas?",
]


def get_json(path: str, params: dict) -> dict:
    url = f"{BASE}{path}?{urlencode(params)}"
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(path: str, payload: dict) -> dict:
    url = f"{BASE}{path}"
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    print(f"Testing Phase 6C against {BASE}")
    print("=" * 78)

    for i, question in enumerate(CASES, 1):
        print(f"\nTEST {i}")
        print("-" * 78)
        print(f"QUESTION: {question}")

        try:
            retrieval = get_json(
                "/api/retrieval",
                {"q": question, "limit": 5, "include_history": "true"},
            )

            print("\nRETRIEVAL:")
            for memory in retrieval.get("active", []):
                content = memory.get("content") or {}
                print(
                    f"  #{memory['id']} [{memory['status']}] "
                    f"{memory['subject']} :: "
                    f"{content} score={memory.get('retrieval_score')}"
                )

            answer = post_json(
                "/api/hey-kivi",
                {"question": question, "limit": 8},
            )

            print("\nHEY KIVI:")
            print(f"  VERDICT: {answer.get('evidence_verdict')}")
            print(f"  DECISION: {answer.get('decision')}")
            print(f"  ANSWER: {answer.get('answer')}")
            print(f"  REASON: {answer.get('evidence_reason')}")
            print(f"  MEMORIES: {answer.get('memory_ids')}")
            print(f"  SOURCES: {answer.get('source_transcript_ids')}")
            print(f"  LATENCY: {answer.get('latency_ms')} ms")

        except HTTPError as exc:
            print(f"HTTP ERROR: {exc.code} {exc.reason}")
            try:
                print(exc.read().decode("utf-8"))
            except Exception:
                pass
            return 1
        except URLError as exc:
            print(f"CONNECTION ERROR: {exc.reason}")
            return 1
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")
            return 1

    print("\n" + "=" * 78)
    print("Phase 6C retrieval + Hey Kivi tests completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
