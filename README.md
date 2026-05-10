# Jailbreak Autoresearch

A small autoresearch loop for prompt-harness experiments.

The repo tests whether different header/footer harnesses change how target
models answer one fixed body. Each experiment stores the harness, response,
score, and model-role permutation in SQLite.

## Before You Run

Customize these two root files:

- `example.md` — the body/prompt you want to test.
- `desired-output.md` — the scoring rubric describing what a good answer
  should look like.

The runner always uses `example.md` as the body and `desired-output.md` as the
verifier. Keep them in sync.

Every generated footer is normalized to end with:

```text
Answer with exactly one sentence.
```

## Setup

Create `.env`:

```bash
OPENROUTER_API_KEY=your_key_here
```

Run a dry smoke test:

```bash
python3 run.py --all-strategies --max-permutations 1 --dry-run
```

Run one live baseline:

```bash
python3 run.py --strategy baseline --max-permutations 1
```

Run all strategies on one role permutation:

```bash
python3 run.py --all-strategies --max-permutations 1
```

Summarize results:

```bash
python3 report.py
```

Results are written to `runs/experiments.sqlite`.

## How It Works

1. `run.py` chooses target, researcher, and scorer models from `models.json`.
2. The researcher proposes a candidate multi-turn harness.
3. The target model receives the harness with `example.md` inserted as the
   final body.
4. The scorer compares the response to `desired-output.md` and returns a
   score from `0.0` to `1.0`.
5. Winning fragments are stored and reused by later strategies.

Strategies:

- `baseline` — no harness.
- `seeded` — seed headers/footers from `prompts/headers/` and
  `prompts/footers/`.
- `evolve-best` — mutate the strongest prior harness.
- `recombine` — recombine strong fragments from prior runs.

## Files

- `example.md` — your active test body.
- `desired-output.md` — your active scoring rubric.
- `models.json` — OpenRouter model list.
- `src/` — runner, prompt, strategy, scoring, and storage code.
- `tests/` — invariant tests.
- `runs/` — local experiment database, ignored by git.

## Notes

- Do not commit real API keys.
- Do not commit private experiment databases.
- Use only test bodies you are authorized to evaluate.
