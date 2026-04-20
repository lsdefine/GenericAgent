# Web Browsing Benchmark Data

Per-task runs underlying **Section 4.5 — Web Browsing Capability** of the GA technical report. This folder covers the two public benchmarks whose per-task scores are released; the 22-task **Custom Tasks** set reported in the paper is not redistributed here.

## Benchmarks

| Benchmark | Tasks | Evaluation | Notes |
|---|---:|---|---|
| **WebCanvas** | 12 | Automatic URL/state checkpoints | Fundamental browser interactions (navigation, clicking, filtering, extraction) |
| **BrowseComp-ZH** | 10 | LLM-as-a-judge | Multi-hop, chain-based reasoning over the Chinese web |

Both systems (GA and OpenClaw) use **Claude Opus 4.6** as the backbone, on exactly the same 22 questions.

## Files

| File | Description |
|---|---|
| `data.py` | Per-task scores, turns, runtime, and token counts for GA and OpenClaw on both benchmarks |
| `generate_charts.py` | Plotting script that consumes `data.py` |
| `comparison.png` | Pre-rendered composite chart |
| `comparison_report.md` | Full Chinese comparison report summarizing success rate, efficiency, and per-task wins/losses |

## Headline numbers (from `comparison_report.md`)

| Metric | GA | OpenClaw |
|---|---|---|
| BrowseComp-ZH accuracy | **60.0%** (6/10) | 20.0% (2/10) |
| WebCanvas average score | **83.4%** | 72.2% |
| Average tokens (BrowseComp-ZH) | **471K** | 1,313K |
| Average tokens (WebCanvas) | **185K** | 707K |

Across both benchmarks, OpenClaw's token consumption is **3.1×** higher than GA's, while GA wins 8 of 22 tasks head-to-head (vs. 2 wins for OpenClaw, 12 ties).
