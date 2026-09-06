from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

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

def get(path: str, params: dict):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def main() -> int:
    print(f"Testing Phase 6D against {BASE}\n" + "=" * 78)
    for i, question in enumerate(CASES, 1):
        print(f"\nTEST {i}\n{'-' * 78}\nQUESTION: {question}\n")
        data = get("/api/retrieval", {"q": question, "limit": 5})
        print("RETRIEVAL:")
        for m in data.get("active", []):
            print(f"  #{m['id']} [{m['status']}] {m['subject']} :: {m['content']} score={m.get('retrieval_score')}")
        answer = get("/api/hey-kivi", {"question": question, "limit": 8}) if False else None
        # POST without third-party dependencies.
        body = json.dumps({"question": question, "limit": 8}).encode()
        req = urllib.request.Request(BASE + "/api/hey-kivi", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            answer = json.loads(r.read().decode())
        print("\nHEY KIVI:")
        print("  VERDICT:", answer.get("evidence_verdict"))
        print("  DECISION:", answer.get("decision"))
        print("  ANSWER:", answer.get("answer"))
        print("  SOURCE IDS:", answer.get("source_transcript_ids"))
        print("  PROVENANCE ENTRIES:", len(answer.get("provenance", [])))
        print("  LATENCY:", answer.get("latency_ms"), "ms")
    print("\n" + "=" * 78 + "\nPhase 6D tests completed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
