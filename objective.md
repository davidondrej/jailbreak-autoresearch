# Objective

Build and run a simple autoresearch loop that searches for header/footer
harnesses that improve a target model's score against one user-supplied test
body.

## Active Inputs

- `example.md` — the body to test.
- `desired-output.md` — the rubric used by the scorer.

The framework assumes these two files are edited together. If you replace the
body, replace the rubric too.

## Success Signal

A harness is better when its mean score improves over the no-harness baseline
for the same `(target, researcher, scorer)` role permutation.

The scorer receives:

- the model response
- `desired-output.md`

and returns a float in `[0.0, 1.0]`.

## Strategies

- `baseline` — send only the body plus fixed footer closer.
- `seeded` — test seed headers/footers.
- `evolve-best` — mutate the best prior harness.
- `recombine` — combine strong fragments from previous runs.

## Validation

Code validation:

```bash
python3 -m unittest -q
```

Experiment run:

```bash
python3 run.py --all-strategies --max-permutations 1
python3 report.py
```

## Constraints

- Keep the code small.
- Do not add dependencies unless necessary.
- Do not commit `.env`, `runs/`, API keys, or private experiment data.
- Keep `example.md` and `desired-output.md` as the public template interface.
