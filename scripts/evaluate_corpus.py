#!/usr/bin/env python3
"""Run a transcript corpus through Kivi and produce reproducible evaluation metrics.

The evaluator talks to the same HTTP API used by the application/importer. It does
not write to SQLite directly. By default it leaves the existing database intact;
use --reset when a clean evaluation run is desired.

Examples:
    python scripts/evaluate_corpus.py --file corpus/dev_30.jsonl --reset
    python scripts/evaluate_corpus.py --file corpus/eval_500.jsonl --reset
    python scripts/evaluate_corpus.py --file corpus/dev_30.jsonl \
        --expected corpus/dev_30_expected.json --reset

Outputs (unless --output is supplied):
    evaluation/results/<corpus-name>_report.json
    evaluation/results/<corpus-name>_report.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def request_json(base_url: str, method: str, path: str, payload: dict | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to Kivi at {base_url}. Is the server running?"
        ) from exc


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def load_jsonl(path):
    records = []

    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid JSON on line {line_number} of {path}: {e}"
                ) from e

    return records


def load_corpus(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc
        for field in ("timestamp", "raw_asr", "formatted_text"):
            if field not in record:
                raise ValueError(f"Corpus line {line_no} is missing required field: {field}")
        records.append(record)
    if not records:
        raise ValueError(f"Corpus is empty: {path}")
    return records


def normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def subject_key(value: Any) -> str:
    value = normalize(value)
    if value.startswith("project "):
        value = value[len("project "):]
    return value


def memory_identity(memory: dict[str, Any]) -> tuple[str, str, str]:
    content = memory.get("content") or {}
    return (
        normalize(memory.get("type")),
        subject_key(memory.get("subject")),
        normalize(content.get("attribute")),
    )


def reset_database() -> None:
    subprocess.run(
        [sys.executable, "-m", "scripts.reset_db"],
        cwd=ROOT,
        check=True,
    )


def fetch_all_memories(base_url: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for status in ("ACTIVE", "UNCERTAIN", "SUPERSEDED", "DELETED"):
        result.extend(request_json(base_url, "GET", f"/api/memories?status={status}&limit=5000"))
    return result


def fetch_all_decisions(base_url: str) -> list[dict[str, Any]]:
    return request_json(base_url, "GET", "/api/memory-decisions?limit=5000")


def evaluate(
    base_url: str,
    records: list[dict[str, Any]],
    expected: dict[str, Any] | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    record_results: list[dict[str, Any]] = []
    latencies: list[float] = []
    errors = 0

    for index, record in enumerate(records, 1):
        payload = {
            "timestamp": record["timestamp"],
            "raw_asr": record["raw_asr"],
            "formatted_text": record["formatted_text"],
            "metadata": {
                **record.get("metadata", {}),
                "corpus_record_id": record.get("id", f"record-{index:03d}"),
            },
        }

        try:
            transcript = request_json(base_url, "POST", "/api/transcripts", payload)
            t0 = time.perf_counter()
            result = request_json(
                base_url,
                "POST",
                f"/api/transcripts/{transcript['id']}/process-memory",
                {},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)

            decision = result["decision"]["decision"]
            expected_item = expected.get(record.get("id"), {}) if expected else {}
            expected_decision = expected_item.get("expected_decision")

            record_results.append(
                {
                    "corpus_id": record.get("id", f"record-{index:03d}"),
                    "transcript_id": transcript["id"],
                    "decision": decision,
                    "expected_decision": expected_decision,
                    "match": (
                        decision == expected_decision
                        if expected_decision is not None
                        else None
                    ),
                    "memory_id": result["decision"].get("memory_id"),
                    "superseded_memory_id": result["decision"].get("superseded_memory_id"),
                    "decision_reason": result["decision"].get("reason"),
                    "extraction": result.get("extraction"),
                    "model": result.get("model"),
                    "latency_ms": round(elapsed_ms, 3),
                }
            )
            print(
                f"{record.get('id', index):>12}  "
                f"transcript={transcript['id']:>4}  "
                f"decision={decision:<9}  "
                f"latency={elapsed_ms:>8.1f}ms"
            )
        except Exception as exc:  # keep evaluating remaining records
            errors += 1
            record_results.append(
                {
                    "corpus_id": record.get("id", f"record-{index:03d}"),
                    "error": str(exc),
                }
            )
            print(f"{record.get('id', index):>12}  ERROR: {exc}", file=sys.stderr)

    elapsed_total_ms = (time.perf_counter() - started) * 1000.0
    decisions = Counter(
        item["decision"] for item in record_results if "decision" in item
    )

    memories = fetch_all_memories(base_url)
    active_memories = [m for m in memories if m.get("status") == "ACTIVE"]
    uncertain_memories = [m for m in memories if m.get("status") == "UNCERTAIN"]
    superseded_memories = [m for m in memories if m.get("status") == "SUPERSEDED"]

    # Detect potentially problematic active-state duplication. Different values for
    # the same semantic identity indicate multiple current states for one property.
    by_identity: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for memory in active_memories:
        by_identity[memory_identity(memory)].append(memory)

    conflicting_active = []
    duplicate_same_value = []
    for identity, group in by_identity.items():
        values = {
            normalize((m.get("content") or {}).get("value"))
            for m in group
        }
        if len(values) > 1:
            conflicting_active.append(
                {
                    "identity": identity,
                    "memory_ids": [m["id"] for m in group],
                    "values": sorted(values),
                }
            )
        elif len(group) > 1:
            duplicate_same_value.append(
                {
                    "identity": identity,
                    "memory_ids": [m["id"] for m in group],
                }
            )

    # Pull traces only for memories touched by this evaluation. This measures whether
    # decisions that claim to create/update/retain/uncertain have source evidence.
    touched_ids = sorted(
        {
            item["memory_id"]
            for item in record_results
            if item.get("memory_id") is not None
        }
    )
    traces: dict[int, dict[str, Any]] = {}
    provenance_missing: list[int] = []
    history_event_counts: Counter[str] = Counter()
    for memory_id in touched_ids:
        try:
            trace = request_json(base_url, "GET", f"/api/memories/{memory_id}")
            traces[memory_id] = trace
            if not trace.get("sources"):
                provenance_missing.append(memory_id)
            for event in trace.get("history", []):
                history_event_counts[event.get("event_type", "UNKNOWN")] += 1
        except Exception:
            provenance_missing.append(memory_id)

    expected_summary = None
    if expected:
        comparisons = [
            item for item in record_results if item.get("expected_decision") is not None
        ]
        matches = sum(1 for item in comparisons if item.get("match"))
        expected_summary = {
            "records_with_expected_decision": len(comparisons),
            "matches": matches,
            "mismatches": len(comparisons) - matches,
            "match_rate": round(matches / len(comparisons), 4) if comparisons else None,
        }

    successful = len(latencies)
    model_providers = Counter()
    model_names = Counter()
    fallback_count = 0
    for item in record_results:
        model = item.get("model") or {}
        provider = model.get("provider")
        model_name = model.get("model")
        if provider:
            model_providers[provider] += 1
        if model_name:
            model_names[model_name] += 1
        if provider == "fallback" or "llm_error" in model:
            fallback_count += 1

    report = {
        "evaluation": {
            "corpus": str(records[0].get("id", "")) if records else "",
            "record_count": len(records),
            "processed_successfully": successful,
            "errors": errors,
            "started_at_epoch": time.time(),
            "total_elapsed_ms": round(elapsed_total_ms, 3),
        },
        "decisions": dict(sorted(decisions.items())),
        "decision_rates": {
            key: round(value / successful, 4) if successful else None
            for key, value in sorted(decisions.items())
        },
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 3) if latencies else None,
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 3) if latencies else None,
            "min": round(min(latencies), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
        },
        "model_usage": {
            "providers": dict(model_providers),
            "models": dict(model_names),
            "fallback_or_llm_error_count": fallback_count,
        },
        "memory_state": {
            "total": len(memories),
            "active": len(active_memories),
            "uncertain": len(uncertain_memories),
            "superseded": len(superseded_memories),
            "deleted": sum(1 for m in memories if m.get("status") == "DELETED"),
            "by_type": dict(Counter(m.get("type") for m in memories)),
        },
        "state_quality": {
            "active_conflicting_identities": len(conflicting_active),
            "active_duplicate_same_value_identities": len(duplicate_same_value),
            "provenance_checked_memories": len(touched_ids),
            "provenance_missing_memories": len(provenance_missing),
            "history_events": dict(sorted(history_event_counts.items())),
        },
        "active_conflicts": conflicting_active,
        "active_duplicates": duplicate_same_value,
        "provenance_missing_memory_ids": provenance_missing,
        "expected": expected_summary,
        "records": record_results,
    }
    return report


def markdown_report(report: dict[str, Any]) -> str:
    evaluation = report["evaluation"]
    decisions = report["decisions"]
    latency = report["latency_ms"]
    state = report["memory_state"]
    quality = report["state_quality"]
    expected = report.get("expected")

    lines = [
        "# Kivi Corpus Evaluation Report",
        "",
        "## Summary",
        "",
        f"- Records: **{evaluation['record_count']}**",
        f"- Processed successfully: **{evaluation['processed_successfully']}**",
        f"- Errors: **{evaluation['errors']}**",
        f"- Total processing time: **{evaluation['total_elapsed_ms']:.1f} ms**",
        "",
        "## Decisions",
        "",
        "| Decision | Count | Rate |",
        "|---|---:|---:|",
    ]
    for decision, count in decisions.items():
        lines.append(f"| {decision} | {count} | {report['decision_rates'][decision]:.1%} |")

    lines += [
        "",
        "## Latency",
        "",
        f"- Mean: **{latency['mean']} ms**",
        f"- Median: **{latency['median']} ms**",
        f"- P95: **{latency['p95']} ms**",
        f"- Min / max: **{latency['min']} / {latency['max']} ms**",
        "",
        "## Memory State",
        "",
        f"- Total: **{state['total']}**",
        f"- Active: **{state['active']}**",
        f"- Uncertain: **{state['uncertain']}**",
        f"- Superseded: **{state['superseded']}**",
        f"- Deleted: **{state['deleted']}**",
        "",
        "### By type",
        "",
        "| Type | Count |",
        "|---|---:|",
    ]
    for memory_type, count in sorted(state["by_type"].items()):
        lines.append(f"| {memory_type} | {count} |")

    lines += [
        "",
        "## State Quality",
        "",
        f"- Active conflicting identities: **{quality['active_conflicting_identities']}**",
        f"- Active duplicate same-value identities: **{quality['active_duplicate_same_value_identities']}**",
        f"- Memories checked for provenance: **{quality['provenance_checked_memories']}**",
        f"- Memories missing provenance: **{quality['provenance_missing_memories']}**",
        "",
        "### History events",
        "",
        "| Event | Count |",
        "|---|---:|",
    ]
    for event, count in quality["history_events"].items():
        lines.append(f"| {event} | {count} |")

    if expected is not None:
        lines += [
            "",
            "## Expected Decision Comparison",
            "",
            f"- Records with expected labels: **{expected['records_with_expected_decision']}**",
            f"- Matches: **{expected['matches']}**",
            f"- Mismatches: **{expected['mismatches']}**",
            f"- Match rate: **{expected['match_rate']:.1%}**" if expected["match_rate"] is not None else "- Match rate: **N/A**",
            "",
            "> Expected labels are an evaluation aid; semantic correctness should be reviewed for mismatches rather than optimizing blindly for label agreement.",
        ]

    if report["active_conflicts"]:
        lines += [
            "",
            "## Active State Conflicts",
            "",
            "The following semantic identities have more than one active value:",
            "",
        ]
        for conflict in report["active_conflicts"]:
            lines.append(
                f"- `{conflict['identity']}` → memories {conflict['memory_ids']}; values: {conflict['values']}"
            )

    if report["provenance_missing_memory_ids"]:
        lines += [
            "",
            "## Missing Provenance",
            "",
            f"Memory IDs: {report['provenance_missing_memory_ids']}",
        ]

    lines += [
        "",
        "## Reproducibility",
        "",
        "This report was produced by `scripts/evaluate_corpus.py` through the running Kivi HTTP API.",
        "",
    ]
    return "\n".join(lines)



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Path to JSONL corpus")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--expected",
        help="Optional JSON expected-decision file, e.g. corpus/dev_30_expected.json",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the local SQLite database before evaluation",
    )
    parser.add_argument(
        "--output",
        help="Output prefix. Writes <prefix>.json and <prefix>.md",
    )
    args = parser.parse_args()

    corpus_path = Path(args.file)
    if not corpus_path.exists():
        print(f"Corpus file not found: {corpus_path}", file=sys.stderr)
        return 1

    try:
        records = load_corpus(corpus_path)
        expected = None
        if args.expected:
            expected_path = Path(args.expected)
            if not expected_path.exists():
                print(f"Expected file not found: {expected_path}", file=sys.stderr)
                return 1
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
        if args.reset:
            print("Resetting local database...")
            reset_database()

        request_json(args.base_url, "GET", "/health")
        print(f"\nEvaluating {len(records)} records from {corpus_path}\n")
        report = evaluate(args.base_url, records, expected)

        if args.output:
            prefix = Path(args.output)
        else:
            prefix = ROOT / "evaluation" / "results" / f"{corpus_path.stem}_report"
        prefix.parent.mkdir(parents=True, exist_ok=True)

        json_path = prefix.with_suffix(".json")
        md_path = prefix.with_suffix(".md")
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(markdown_report(report), encoding="utf-8")

        print("\nEvaluation complete.")
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {md_path}")
        return 0 if report["evaluation"]["errors"] == 0 else 2
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
