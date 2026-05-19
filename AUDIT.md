```markdown
# AUDIT.md

## Executive Summary

`jailbreak-autoresearch` is a small, well-scoped autoresearch loop that mutates header/footer/multi-turn harnesses around a fixed `example.md` body and scores target-model responses against `desired-output.md`. The plumbing (storage, fragments, lift reporting, role-permutation sweeps) is solid. The bottleneck for testing more "radical" prompts is concentrated in **one place**: the researcher is invoked with `temperature=0.9` against a single anchor researcher model (Claude Sonnet 4.6) that itself RLHF-refuses many radical harness families, then the *researcher's own response* is fed into a strict JSON validator with no refusal-detection and no model fallback. When the anchor researcher soft-refuses or sanitizes a palette family (e.g. payload splitting, authority impersonation, persona/DAN), the loop silently degrades to `fallback_harness` — a bland recombination of past fragments — and the palette family is effectively never explored.

The single highest-leverage change is to **detect researcher self-censorship and rotate to a less-aligned researcher model** before falling back, so radical palette families actually reach the target.

## Findings (ordered by severity)

### 1. (Highest impact) Researcher anchor is the chokepoint for radical prompts
`src/strategies.py::researcher_harness` retries up to 3 times against `roles.researcher`, then raises and `candidates_for_strategy` calls `fallback_harness`, which produces a tame harness built from past fragments. The default anchor in `run.py::choose_researcher_anchor` is `anthropic/claude-sonnet-4.6` (`RESEARCHER_ANCHOR_PREFERENCES[0]`) — the model most likely to refuse to author radical harnesses (DAN personas, payload splitting, authority impersonation, GODMODE/L1B3RT4S patterns). Symptoms:

- No detection of researcher refusals. A response like *"I can't help craft a jailbreak"* will pass `extract_json_with_repair` only if it contains a JSON-shaped blob; otherwise it triggers the fallback path silently.
- Even when JSON is returned, the researcher often sanitizes the chosen `family_hint`. There is no check that the produced harness actually reflects the requested palette family.
- `multiturn_validation_error` and `contains_eval_tell` enforce structure but not *radicality*. A sanitized "polite roleplay" harness passes all gates.

### 2. `family_hint` is requested but not enforced
`choose_family_hint` rotates families deterministically, but the researcher is free to ignore it. There is no post-hoc check that the produced header/footer/turns embody the requested family. Combined with finding #1, the deterministic rotation creates an *illusion* of palette coverage in the database while the actual harnesses cluster around the researcher's comfort zone (benign roleplay, technical-continuation framings).

### 3. Fallback harness is a regression to the mean
`fallback_harness` in `src/strategies.py` reuses prior winning fragments. Because early winners tend to be the tamest harnesses that any researcher will author, this creates a positive feedback loop: radical families fail → fallback uses tame fragments → tame fragments dominate `top_fragments` → future `recombine` runs are even tamer.

### 4. Temperature and `candidate_limit=1` undersample the palette
`run.py` defaults `--candidate-limit 1`, and the researcher is called once per (strategy, iteration). At `temperature=0.9` a single sample is high variance but low coverage — there is no best-of-N to surface a radical proposal when the first sample is a soft refusal.

### 5. Eval-tell ban is one-directional
`EVAL_TELL_PHRASES` correctly forbids evaluator framing, but there is no symmetric ban on *researcher self-censorship tells* ("I'll keep this safe", "for educational purposes only", "I cannot help with bypassing"). These markers are strong signals that the harness has been neutered.

### 6. Minor: scorer fragility on radical outputs
`src/scoring.py::parse_score` falls back to regex `[0,1]`, which can mis-score responses that contain digits (e.g. step-numbered radical content) when the JSON path fails. Low severity but worth noting because radical responses are exactly the ones most likely to break strict JSON.

---

## Targeted Recommendation (the single change)

**Rotate the researcher model when it self-censors or fails to produce a palette-faithful harness, before falling back to tame fragments.**

Concretely, in `src/strategies.py`:

1. Add a `RESEARCHER_FALLBACK_CHAIN` (e.g. `["deepseek/deepseek-v4-pro", "x-ai/grok-4.3", "google/gemini-3.1-flash-lite", "anthropic/claude-sonnet-4.6", "openai/gpt-5.5"]` — ordered by empirically observed willingness to author adversarial harnesses; DeepSeek and Grok first).
2. Add a `RESEARCHER_SELF_CENSOR_PHRASES` tuple (e.g. `"i can't help", "i cannot help", "i won't", "as an ai", "for educational purposes", "i'll keep this safe", "harmless alternative", "ethical guidelines"`) and a `contains_self_censor()` helper mirroring `contains_eval_tell()`.
3. In `researcher_harness`, on each of the 3 attempts: if the raw researcher content trips `contains_self_censor`, *or* `multiturn_validation_error` returns non-empty, *or* `extract_json_with_repair` raises — advance to the next model in the chain instead of just retrying the same model.
4. Add a lightweight palette-faithfulness check: after producing a candidate, require that at least one of the family's signature tokens (e.g. for "Persona / roleplay": `DAN|AIM|unrestricted|jailbroken|godmode`; for "Payload splitting": presence of unicode tag chars or split-letter patterns) appears somewhere in the assembled turns. On miss, treat as a soft failure and rotate model.

File touch list for the change:
- `src/strategies.py` — the rotation logic, self-censor detector, palette signature map.
- `run.py` — pass the full `models` list (or a researcher chain derived from it) into `RoleModels` or a new field so `researcher_harness` can rotate. Cleanest: extend `RoleModels` with `researcher_chain: tuple[str, ...]` and have `run.py` populate it from `choose_researcher_anchor` + remaining models.
- `tests/test_invariants.py` — add a test that a self-censoring fake client triggers rotation rather than fallback.

This is one change, bounded to the researcher dispatch layer, and directly attacks the reason radical palette families never reach the target.

---

## Pragmatic Next-Steps Checklist

- [ ] Add `RESEARCHER_FALLBACK_CHAIN` and `contains_self_censor()` in `src/strategies.py`.
- [ ] Extend `RoleModels` (or thread a chain via `candidates_for_strategy`) so rotation has access to alternative researchers from `models.json`.
- [ ] Replace the "retry same model 3x" loop in `researcher_harness` with "try next model in chain on self-censor / validation / palette-miss".
- [ ] Add a `family_signature_present(harness, family)` check; on miss, rotate model rather than accept.
- [ ] Bump default `--candidate-limit` to 2–3 for non-baseline strategies, or add best-of-N sampling inside `researcher_harness` only when the first sample self-censors.
- [ ] Log the *researcher model actually used* per experiment row (new column `researcher_model_used`) so `report.py` can show which researchers produce which lifts. Currently `researcher_model` is the anchor, which will become misleading after rotation.
- [ ] Add a unit test: fake client that self-censors on call 1 and complies on call 2 → assert harness comes from the second model and bypasses `fallback_harness`.
- [ ] Tighten `parse_score` to prefer JSON and only fall back to regex when the response is clearly numeric (low priority, but reduces noise on radical outputs).
- [ ] After the change lands, run `python3 run.py --all-strategies --max-permutations 1` and confirm `report.py` shows non-trivial lift on at least one resistant target with a non-Claude researcher cell.
```