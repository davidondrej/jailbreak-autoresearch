# docs-autoresearch
Andrej Karpathy’s **“auto research”** is actually his open-source repo **`karpathy/autoresearch`**.

It is a minimal experiment where an AI coding agent runs ML research loops by itself: it edits model-training code, trains for 5 minutes, checks if validation loss improved, keeps the change if it helped, reverts it if it failed, then repeats overnight. Karpathy describes it as giving an agent “a small but real LLM training setup” and letting it experiment autonomously. ([GitHub][1])

## The core idea

Instead of a human researcher manually changing architecture, optimizer settings, hyperparameters, etc., the human writes a **research instruction file** and the AI agent does the repetitive experimentation.

The loop is basically:

1. Agent reads the research instructions.
2. Agent edits `train.py`.
3. Agent commits the change.
4. Agent runs training for a fixed 5 minutes.
5. It measures `val_bpb`, meaning validation bits-per-byte.
6. If `val_bpb` is lower, the change stays.
7. If it is worse or crashes, the agent reverts the change.
8. Repeat forever.

The repo says the metric is **validation bits per byte**, lower is better, and the fixed 5-minute training budget makes experiments comparable. ([GitHub][1])

## The architecture is intentionally tiny

Karpathy kept the repo small. The important files are:

**`prepare.py`**
This is fixed. It handles data prep, tokenizer, dataloader, and evaluation. The agent is not supposed to modify it. ([GitHub][1])

**`train.py`**
This is the sandbox. The agent can change architecture, optimizer, batch size, hyperparameters, model depth, training loop, etc. It contains the GPT model and optimizer logic. ([GitHub][1])

**`program.md`**
This is the “agent instruction file.” The human edits this, not the Python code. It tells the agent how to run experiments, what counts as success, what files it can touch, how to log results, and when to revert. Karpathy calls it basically a lightweight “skill.” ([GitHub][1])

## The key mechanism: a greedy research ratchet

The agent runs on a Git branch. Every experiment is a commit. If the result improves, the branch advances. If it fails, the commit is reset. So Git becomes the memory and selection mechanism.

The default `program.md` explicitly tells the agent to loop forever, modify only `train.py`, run `uv run train.py`, parse `val_bpb`, log results to `results.tsv`, keep improvements, and reset worse changes. It also says not to ask the human whether to continue, because the human may be asleep. ([GitHub][2])

This is why people call it a **ratchet loop**: the codebase only moves forward when the measured metric improves.

## Why this is interesting

This is **not just AutoML**.

Traditional AutoML usually searches over a predefined space: learning rates, architectures, batch sizes, etc. AutoResearch gives the coding agent freedom to change arbitrary code inside `train.py`. So the search space is not a fixed config grid; it is “whatever the LLM can propose and implement.” DataCamp summarizes this distinction clearly: AutoResearch is not classical hyperparameter tuning because the agent can modify arbitrary code. ([DataCamp][3])

The deeper idea is:

> research becomes an eval loop.

You define:

* editable system
* immutable evaluator
* clear metric
* fast experiment cycle
* automatic keep/revert rule
* agent that proposes mutations

That pattern can apply beyond LLM training.

## Requirements

The official README says it needs a **single NVIDIA GPU**, Python 3.10+, and `uv`; it was tested on H100. Setup is roughly `uv sync`, `uv run prepare.py`, then `uv run train.py`. After that, you launch Claude Code, Codex, or another coding agent inside the repo and tell it to read `program.md`. ([GitHub][1])

Karpathy estimates roughly **12 experiments per hour** and about **100 experiments while you sleep**, because each experiment is fixed to 5 minutes. ([GitHub][1])

## How to actually start the loop

**There is no orchestration script, daemon, or scheduler.** The loop lives inside the coding agent's own tool-use cycle — `program.md` just hijacks it and tells the agent never to terminate.

Exact kickoff after scaffolding is done:

1. `cd` into the repo.
2. Open Claude Code (or Codex / OpenCode / Cursor) inside it.
3. **Disable permission prompts** (Claude Code: `--dangerously-skip-permissions`). The loop dies if every edit needs approval.
4. Send one message — Karpathy's literal recommended kickoff:
   > "Hi, have a look at `program.md` and let's kick off a new experiment! Let's do the setup first."
5. Walk away.

To resume later: open the agent in the repo and say "continue the autoresearch loop, check `results.tsv` and `program.md` for context." Git history is the state.

**Driver reliability:** Karpathy's README notes Codex doesn't reliably follow "NEVER STOP" — it tends to halt after a few experiments. **Claude Code is the recommended driver.**

## What it can discover

It can find incremental improvements like:

* better optimizer settings
* architecture tweaks
* attention changes
* model depth / width tradeoffs
* batch size changes
* regularization tweaks
* faster training changes

Karpathy later posted that a roughly 2-day run on a depth-12 model found around 20 changes that improved validation loss. ([X (formerly Twitter)][4])

## Its biggest weakness

It is greedy.

Because it only keeps changes that immediately improve the metric, it can get stuck in local optima. A change that temporarily worsens results but enables a much better architecture later would be discarded. DataCamp points out this “creativity ceiling”: the loop tends to find incremental improvements, not necessarily deep novel research breakthroughs. ([DataCamp][3])

Also, the agent can overfit the metric, make ugly hacks, or exploit weak evaluations. So the evaluator becomes the most important part of the system.

## The bigger vision

Karpathy hinted that the next step is **massively collaborative distributed autoresearch**, something like SETI@home but for AI agents doing experiments across many machines. ([X (formerly Twitter)][5])

Shopify also generalized the idea beyond model training: they used the same pattern to improve engineering metrics like build time, where the loop is “change code → measure metric → keep/revert → repeat.” ([Shopify][6])

## My practical take

The important invention is not the LLM training repo itself.

The important invention is the **template**:

```text
Human writes research objective
Agent modifies one bounded part of the system
Evaluator measures objective score
Git keeps good mutations and reverts bad ones
Loop runs autonomously
```

For your world, this pattern is very relevant. You could use the same structure for:

* improving YouTube title/thumbnail prediction models
* optimizing onboarding conversion
* optimizing cold outreach copy against reply-rate evals
* improving agent workflows in Vectal
* benchmarking different prompt / tool / memory designs
* automatically reducing latency or cost in an AI SaaS

But it only works if the metric is real, fast, and hard to game. That is the whole bottleneck.

[1]: https://github.com/karpathy/autoresearch "GitHub - karpathy/autoresearch: AI agents running research on single-GPU nanochat training automatically · GitHub"
[2]: https://github.com/karpathy/autoresearch/blob/master/program.md "autoresearch/program.md at master · karpathy/autoresearch · GitHub"
[3]: https://www.datacamp.com/tutorial/guide-to-autoresearch "A Guide to Andrej Karpathy’s AutoResearch: Automating ML with AI Agents | DataCamp"
[4]: https://x.com/karpathy/status/2031135152349524125?utm_source=chatgpt.com "Three days ago I left autoresearch tuning nanochat for"
[5]: https://x.com/karpathy/status/2030705271627284816?utm_source=chatgpt.com "Andrej Karpathy"
[6]: https://shopify.engineering/autoresearch "Autoresearch isn’t just for training models (2026) - Shopify"
