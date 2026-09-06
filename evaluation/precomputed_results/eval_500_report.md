# Kivi Corpus Evaluation Report

## Summary

- Records: **500**
- Processed successfully: **500**
- Errors: **0**
- Total processing time: **1852914.5 ms**

## Decisions

| Decision | Count | Rate |
|---|---:|---:|
| CREATE | 180 | 36.0% |
| REJECT | 72 | 14.4% |
| RETAIN | 162 | 32.4% |
| UNCERTAIN | 43 | 8.6% |
| UPDATE | 43 | 8.6% |

## Latency

- Mean: **3678.337 ms**
- Median: **3069.822 ms**
- P95: **7708.533 ms**
- Min / max: **1614.544 / 11275.595 ms**

## Memory State

- Total: **266**
- Active: **181**
- Uncertain: **42**
- Superseded: **43**
- Deleted: **0**

### By type

| Type | Count |
|---|---:|
| EPISODE | 38 |
| FACT | 188 |
| PREFERENCE | 40 |

## State Quality

- Active conflicting identities: **0**
- Active duplicate same-value identities: **13**
- Memories checked for provenance: **266**
- Memories missing provenance: **0**

### History events

| Event | Count |
|---|---:|
| CREATED | 266 |
| REINFORCED | 162 |
| SUPERSEDED | 43 |

## Expected Decision Comparison

- Records with expected labels: **500**
- Matches: **278**
- Mismatches: **222**
- Match rate: **55.6%**

> Expected labels are an evaluation aid; semantic correctness should be reviewed for mismatches rather than optimizing blindly for label agreement.

## Reproducibility

This report was produced by `scripts/evaluate_corpus.py` through the running Kivi HTTP API.
