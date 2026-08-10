# HEC Tracking SOP

Every HEC phase must follow this sequence:

```text
Charter
    -> Status
    -> Research Notes
    -> Hypothesis
    -> Experiment
    -> Code
    -> Tests
    -> Benchmark
    -> Decision
    -> Status update
    -> Commit
    -> Push
```

## Charter

The charter records long-term architecture principles. Do not change it just to match one experiment result.

## Status

`docs/HEC_STATUS.md` is the first entry point. Keep it short and update it with the current phase, status, latest result, decision, blockers, next phase, and latest commit.

## Research Notes

`docs/HEC_RESEARCH_NOTES.md` records detailed research evidence. Each experiment should include hypothesis, experiment, evidence, benchmark, interpretation, and decision.

## Code

Only implement the minimal code change required by the current experiment. Do not start the next phase through incidental runtime changes.

## Tests

Tests must cover regressions introduced or clarified by the phase. They should verify behavior, not just import success.

## Benchmark

Benchmarks validate the hypothesis. Do not change expected results to make a benchmark appear successful.

## Decision

Every experiment ends with exactly one of:

```text
KEEP
MODIFY
REJECT
```

The decision must be based on the recorded evidence and benchmark result.

## Commit And Push

Before committing, run:

```bash
git diff --check
git status --short --untracked-files=all
git diff --cached --name-only
```

Stage only the files intended for the phase. Do not include unrelated working-tree changes such as `frontends/stapp.py`.

Use HEC-specific commit messages, for example:

```text
HEC Phase 3: normalize executive state
HEC: establish development tracking
```

Do not force push, overwrite remote history, modify credentials, or bypass authentication or branch protection.
