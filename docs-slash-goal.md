# Codex `/goal` — Complete Reference

A practical guide to OpenAI's `/goal` feature in Codex: what it is, when to use it, how to write instructions for it, and how to actually launch a run.

---

## 1. What `/goal` is

`/goal` is a slash command in **Codex CLI v0.128.0+** (shipped April 30, 2026). It turns a normal Codex prompt into a **persistent, self-checking agent** that loops:

> plan → act → test → review → iterate

…until your stop condition is met, you pause it, or the token budget runs out. OpenAI internally calls this the "Ralph loop."

**Key difference from a normal prompt:** when Codex finishes a turn but the goal isn't complete, it **auto-continues** instead of waiting for input. A normal prompt runs ~3 turns. A goal runs as many as the contract demands — sometimes for hours, occasionally overnight.

**What it isn't:**
- Not a budget command (no `/goal budget`)
- Not a safety boundary (sandbox/permissions still your job)
- Not "run forever" — it's goal persistence with a verification loop and a completion model
- Not a replacement for `/plan` (use `/plan` to shape the approach pre-flight; `/goal` is the autopilot)

**Goal states tracked internally:** `pursuing`, `paused`, `achieved`, `unmet`, `budget-limited`.

---

## 2. Enabling `/goal`

The Codex app, CLI, and IDE extension share `~/.codex/config.toml`. Enable the flag once and it works everywhere.

### Path A — via the CLI (easiest)

```bash
codex update                          # need 0.128.0+
codex features enable goals           # writes goals = true to config.toml
codex features list | grep goals      # confirm: goals ... true
```

Or inside the CLI TUI, run `/experimental` and toggle goals.

### Path B — via the Codex app

1. Update the app (macOS: in-app update; Windows: Microsoft Store → Downloads).
2. Open **Settings → Configuration → Open config.toml**.
3. Add:
   ```toml
   [features]
   goals = true
   ```
4. Save and restart the app.

### Auth requirement

`/goal` only activates under **ChatGPT auth** (Plus, Pro, Business, Edu, Enterprise). API-key authentication does **not** enable it — the feature depends on the ChatGPT app-server persistence layer.

Plus tier works but the Codex usage limit gets exhausted quickly during long runs. **Pro ($100/mo) is the realistic minimum** for serious goal use.

---

## 3. When to use `/goal`

Use it when **all three are true**:

1. The task takes more than ~30 minutes of mechanical work.
2. There's a **verifiable stop condition** (tests pass, eval score hit, build green, screenshot matches, coverage target met).
3. The repo is **agent-ready**: working build, decent test coverage, an `AGENTS.md` file with conventions.

If your project is a mess, `/goal` will hit walls fast. Fix the project structure before pointing a long-horizon agent at it.

### High-fit workloads

- **Migrations** — Pydantic v1→v2, Node 14→20, framework swaps, package upgrades
- **Coverage lifts** — "raise `src/auth/` from 38% to 75%"
- **TDD feature builds** — implement from a `PLAN.md`, milestone by milestone
- **Refactors** with contract tests — large rename/extract operations
- **Prompt/eval optimization** — iterate prompts against an eval suite until target score
- **Deployment retry loops** — fix until the deploy pipeline is green
- **Bug repro + fix** — reproduce, write the failing test, fix, verify

### Bad fits

- Single-prompt questions
- Exploratory work without a defined outcome
- Vague requests like "improve the codebase"
- Anything where you can't define "done"
- Tasks involving production credentials or destructive operations on shared infra

`/goal` will follow a bad prompt for an hour. The objective is the contract.

---

## 4. How to write an effective `/goal` instruction

This is where 90% of value is gained or lost. A short, vague goal produces results no better than a normal prompt — you've just burned more tokens. A dense, contracted goal produces work that feels like it came from a senior engineer.

### The 4-part contract

Every `/goal` should explicitly name:

1. **Objective** — one sentence, one outcome. Concrete, not aspirational.
2. **Constraints** — what must NOT change (public API, UI, legacy paths), libraries to use/avoid, files off-limits, naming conventions.
3. **Validation command** — the exact shell command that proves progress (`pnpm test`, `npm run eval`, `pytest -q`, `playwright test`, lighthouse scores, etc.).
4. **Stop condition** — explicit and verifiable: "Stop when X passes" or "Stop when score ≥ Y, OR when further changes need product/architecture decisions."

Plus, point Codex at the **files, docs, issue, or `PLAN.md`** it must read first. Tell it to work in **checkpoints** and keep a short progress log.

### Template

```
/goal <one-sentence objective>.
Read first: <files / PLAN.md / issue links>.
Constraints: <what must not change, libraries, conventions>.
Validate after each change with: <exact command>.
Work in checkpoints; log progress briefly each one.
Stop when: <verifiable condition> OR when further changes require human/product input.
```

### Real examples

**Migration:**
```
/goal Migrate this project from Pydantic v1 to v2.
Read first: pyproject.toml, src/, tests/.
Constraints: no public API changes; keep imports backwards-compatible via shims if needed.
Validate after each change with: pytest -q
Work in checkpoints; log progress briefly each one.
Stop when: full pytest suite passes with zero deprecation warnings, OR when a change requires architecture decisions I should make.
```

**Coverage lift:**
```
/goal Raise test coverage in src/auth/ from current ~38% to ≥ 75%.
Read first: src/auth/, existing tests/auth/, AGENTS.md.
Constraints: no new dependencies; mirror existing test style; do not modify production code unless strictly required to make a path testable.
Validate with: pytest --cov=src/auth --cov-report=term-missing
Work in checkpoints; after each, log coverage delta.
Stop when: coverage ≥ 75% AND all tests pass, OR when remaining uncovered code needs design changes.
```

**Eval optimization:**
```
/goal Optimize the prompts in prompts/classifier/ until the eval suite reaches ≥ 90% pass rate.
After each change, run: npm run eval:classifier
Inspect failing cases, keep prompt edits minimal and targeted.
Stop when: target met, OR when further changes would need product/policy guidance.
```

### The meta-prompting trick (highest-leverage move)

Hand-written `/goal` prompts almost always under-specify. Humans write them as if they'll be in the loop — but with `/goal`, you're not. The agent fills in blanks itself, and the blanks compound over hours.

**Fix:** open a second AI session that already has context on your repo (ChatGPT with the project connected, Claude with the codebase loaded, or a separate Codex thread in the same directory). Ask *it* to:

1. Inspect the codebase
2. Identify hidden assumptions, constraints, and edge cases
3. Produce a dense `/goal` prompt following the 4-part contract

Paste the result into Codex. Order-of-magnitude better runs.

### Writing tips

- **One objective, one stop condition.** Not a backlog.
- **Use literal strings** for file paths, commands, issue numbers, API names — keep them exact.
- **Forbid scope creep explicitly.** "Do not refactor unrelated code." "Do not add dependencies."
- **Tell Codex when to stop and ask.** Add: "If [condition], pause and ask before proceeding."
- **Reference checkpoints by name.** "After checkpoint 2 (tests passing on auth module), proceed to..."

---

## 5. Launching a goal — exact mechanics

### Step-by-step

1. **`cd` into the repo.** Goals run scoped to the working directory; validation commands need the right context.
2. **Start the TUI:** run `codex` (just the bare command — opens the interactive terminal UI).
3. **Sign in with ChatGPT** if you haven't. Not API key.
4. **Type `/goal `** in the composer, followed by your full objective. Press Enter.
5. **Walk away.** Codex enters the loop and auto-continues across turns.

### Important

- `/goal` is a **TUI slash command**, not a shell command. `codex exec "/goal ..."` does **not** behave the same way — don't try to launch goals via `exec`.
- Type `/` first to open the slash popup; if `/goal` doesn't autocomplete, the flag isn't on or the version is too old.
- **App users:** same flow inside the app's thread composer.

### Controlling a running goal

All commands are typed in the same composer:

| Command | Effect |
|---|---|
| `/goal` (alone) | View status: current checkpoint, what's verified, what remains, blockers |
| `/goal pause` | Freeze the loop |
| `/goal resume` | Unfreeze (required in v0.129+; paused goals no longer auto-resume) |
| `/goal clear` | Kill the goal entirely |
| `/goal <new objective>` | Replace current goal |
| `Ctrl+C` or new typed message | Auto-pauses; your input always wins priority |

### What happens when budget runs out

Codex doesn't stop abruptly — it enters a **"budget-limited"** state. The runtime steers it toward graceful wrap-up: summarize progress, note what's left, save state. You can `/goal resume` in a new session to continue.

---

## 6. During the run — operational tips

- **Inspect status periodically** with bare `/goal`. A useful status names the current checkpoint, what was verified, what remains, whether Codex is blocked.
- **If status gets vague → tighten the goal.** Don't pile on ad-hoc instructions. `/goal pause`, refine, set a fresh `/goal`.
- **Always review the diff** before merging. Long autonomy = more code to validate, not less. `/goal` increases agent persistence, which makes human oversight more critical, not optional.
- **Run on a worktree or branch.** Never on `main`. Use Codex's worktree feature or `git checkout -b` first.
- **Keep approvals/sandboxing tight.** Default permissions are correct for goal runs; loosen only after you trust a specific repo + workflow.

---

## 7. Recommended first run

Don't start with an overnight migration. Pick a **30-minute scoped task** with an obvious validation command — for example:

> Raise coverage in `src/utils/` from current to 80%, verify with `pytest --cov`. Stop when target hit.

This teaches you how `/goal` actually stops, which is the single most important thing to understand before trusting it on long runs.

After that, graduate to:
1. A bounded refactor (1–2 hours)
2. A small migration (single module)
3. A multi-hour migration or feature build

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/goal` missing from slash popup | Version <0.128.0 | `codex update` |
| Flag on but command missing | Stale process holding old binary | Quit fully and restart `codex` |
| Typed `/goals` (with s) | Wrong name | It's `/goal`, singular |
| Doesn't activate | API-key auth | Sign out, sign in with ChatGPT subscription |
| Stops abruptly with progress summary | Hit token budget — "budget-limited" state | `/goal resume` in new session; or tighten scope |
| Goal drifts off track | Under-specified objective | Pause, replace with a tighter `/goal` |
| Public docs don't list `/goal` | OpenAI hasn't fully documented it yet (open issue #20536) | The feature is shipped; docs are lagging |

---

## 9. Mental model

`/goal` is a **contract enforcer with a verification loop**, not a "run forever" button. The unlock is that you stop writing prompts and start writing **specifications with stop conditions**.

The interaction model shifts from *"answer this prompt"* to *"pursue this outcome."* Spend the time upfront defining "done"; the rest of the run takes care of itself.

If your day has a category of work that looks like *"Codex would handle this great if it just kept going"* — that's exactly what `/goal` is for.

---

## 10. Quick reference card

```
ENABLE
  codex update
  codex features enable goals

LAUNCH
  cd <repo>
  codex
  /goal <4-part contract objective>

CONTROL
  /goal              → status
  /goal pause        → pause
  /goal resume       → resume
  /goal clear        → kill
  Ctrl+C / new msg   → auto-pause

CONTRACT (every goal needs)
  1. Objective         (one sentence)
  2. Constraints       (what NOT to change)
  3. Validation        (exact command)
  4. Stop condition    (verifiable)
```