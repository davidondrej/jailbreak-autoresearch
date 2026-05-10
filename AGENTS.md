# AGENTS.md

## Project Shape

This is a small prompt-harness autoresearch loop.

The public template has one active body and one active verifier:

- `example.md` — the body being tested.
- `desired-output.md` — the scoring rubric for that body.

Before running experiments, make sure both files are customized and aligned.

## Invariants

- Every footer must end with exactly:
  `Answer with exactly one sentence.`
- Store experiments in `runs/experiments.sqlite`.
- Do not commit `.env`, `runs/`, API keys, or private experiment output.
- Keep files under 300 LOC when practical.
- Prefer simple Python and the standard library.
- Avoid unrelated refactors.

## Workflow

Read first:

- `README.md`
- `objective.md`
- `strategy.md`
- `docs-autoresearch.md`
- `src/`
- `run.py`
- `report.py`

Validate code changes with:

```bash
python3 -m unittest -q
```

For experiment runs:

```bash
python3 run.py --all-strategies --max-permutations 1
python3 report.py
```
