# SOP-Bench (Dangerous Goods Subset)

Standard Operating Procedure benchmark used in two experiments of the GA technical report:

- **Section 4.1 — Task Completion and Token Efficiency.** Evaluates the agent's ability to follow a multi-step SOP end-to-end and produce the correct fulfillment decision.
- **Section 4.3.2 — Effectiveness of Condensed Memory.** Uses this same subset to compare No-Memory / Full-Memory / Redundant-Memory / Condensed-Memory configurations.

Source benchmark: Yu et al., *SOP-Bench: Complex Industrial SOPs for Evaluating LLM Agents*.

## Files

| File | Description |
|---|---|
| `sop.txt` | Natural-language SOP (4-step order fulfillment workflow) |
| `test_set_with_outputs.csv` | 20 test cases, each a row that the agent must fill with its decision |
| `tools.py` | Python implementation of the four required tools (`check_inventory`, `validate_customer`, `calculate_shipping`, `make_fulfillment_decision`) |
| `toolspecs.json` | JSON Schema tool specs injected into the agent |
| `README.md.old` | Original prompt template used during evaluation |

## Evaluation

Each task asks the agent to read a row, execute the 4-tool workflow, and write the final decision (one of `fulfill_immediately`, `fulfill_delayed`, `backorder`, `reject`, `manual_review`) into the last column of that row. The **Task Success Rate (TSR)** is the fraction of rows that match the reference label.
