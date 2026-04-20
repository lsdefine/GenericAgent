# LoCoMo

Long-conversation memory benchmark used in **Section 4.3.3 — Long-Term Fact Retention** of the GA technical report, where GA is compared against Mem0, A-MEM, and OpenClaw on long-horizon factual recall and multi-hop reasoning.

Source benchmark: Maharana et al., *Evaluating Very Long-Term Conversational Memory of LLM Agents* (LoCoMo).

## Files

| File | Description |
|---|---|
| `locomo10.json` | First subset of LoCoMo: 10 long-form conversations, each with ~200 QA pairs |

## Schema (per entry)

| Field | Description |
|---|---|
| `sample_id` | Conversation identifier |
| `conversation` | Multi-session dialogue between two speakers |
| `session_summary` / `event_summary` / `observation` | Reference summaries and timeline metadata |
| `qa` | List of question-answer pairs; each item includes `question`, `answer`, `evidence`, and `category` |

## QA categories

| Category | Task type |
|---|---|
| 1 | Single-hop factual recall |
| 2 | Multi-hop reasoning |
| 3 | Temporal reasoning |
| 4 | Open-domain inference |
| 5 | Summarization (**removed** in the GA evaluation to avoid interference from summarization ability) |

## Evaluation

Models are scored with **F1** (correctness / completeness) and **BLEU-1** (lexical similarity) against reference answers, reported separately for Multi-Hop, Temporal, Open-Domain, and Single-Hop tasks.
