#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import sys
import uuid
from pathlib import Path

from src.config import load_models, require_api_key
from src.openrouter import OpenRouterClient
from src.prompts import (
    assistant_turn_count,
    ensure_footer_closer,
    harness_messages_json,
    list_body_names,
    load_body,
    load_verifier,
    materialize_messages,
    turn_count,
)
from src.scoring import score_response
from src.storage import Store
from src.strategies import RoleModels, candidates_for_strategy


STRATEGIES = ["baseline", "seeded", "evolve-best", "recombine"]
RESISTANT_TARGETS = (
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-5.5",
    "google/gemini-3.1-flash-lite",
    "x-ai/grok-4.3",
)
RESEARCHER_ANCHOR_PREFERENCES = (
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-5.5",
    "google/gemini-3.1-flash-lite",
    "deepseek/deepseek-v4-pro",
    "x-ai/grok-4.3",
)


def main() -> int:
    args = parse_args()
    strategies = STRATEGIES if args.all_strategies else [args.strategy]
    models = load_models()
    role_sets = select_roles(models, args)
    bodies = select_bodies(args)
    client = None if args.dry_run else OpenRouterClient(require_api_key(), timeout=args.timeout, retries=args.retries)
    store = Store(Path(args.db) if args.db else None)
    run_id = uuid.uuid4().hex[:12]

    try:
        for roles in role_sets:
            for body_name in bodies:
                body = load_body(body_name)
                verifier = load_verifier(body_name)
                for _ in range(args.iterations):
                    for strategy in strategies:
                        harnesses = candidates_for_strategy(
                            strategy,
                            body,
                            verifier,
                            roles,
                            store,
                            client,
                            args.candidate_limit,
                            args.dry_run,
                        )
                        for harness in harnesses:
                            run_one(run_id, args, store, client, roles, body, verifier, strategy, harness)
    finally:
        store.close()
    return 0


def run_one(run_id, args, store, client, roles, body, verifier, strategy, harness) -> None:
    footer = ensure_footer_closer(harness.footer)
    harness = type(harness)(harness.name, harness.header, footer, harness.turns)
    messages = materialize_messages(harness, body.text)
    try:
        if args.dry_run:
            response = mock_response(strategy, body.name)
            score = mock_score(strategy)
            scorer_raw = json.dumps({"score": score, "reason": "dry-run deterministic mock"})
        else:
            assert client is not None
            try:
                target_result = client.chat(
                    roles.target,
                    messages,
                    temperature=args.target_temperature,
                    max_tokens=args.max_tokens,
                )
                response = target_result.content
            except Exception as exc:
                response = f"TARGET_ERROR: {type(exc).__name__}: {exc}"
                score = 0.0
                scorer_raw = json.dumps(
                    {"score": score, "reason": "target_call_error", "error": response}
                )
            else:
                score, scorer_raw = score_response(client, roles.scorer, verifier, response)
    except Exception as exc:
        response = f"ERROR: {type(exc).__name__}: {exc}"
        score = 0.0
        scorer_raw = json.dumps({"error": response})

    exp_id = store.insert_experiment(
        {
            "run_id": run_id,
            "dry_run": int(args.dry_run),
            "strategy": strategy,
            "candidate_name": harness.name,
            "body_name": body.name,
            "body_sha256": body.sha256,
            "target_model": roles.target,
            "researcher_model": roles.researcher,
            "scorer_model": roles.scorer,
            "max_tokens": args.max_tokens,
            "target_temperature": args.target_temperature,
            "timeout": args.timeout,
            "header": harness.header,
            "footer": footer,
            "messages_json": harness_messages_json(harness),
            "turn_count": turn_count(harness),
            "assistant_turn_count": assistant_turn_count(harness),
            "response": response,
            "score": score,
            "scorer_raw": scorer_raw,
        }
    )
    print(
        f"id={exp_id} score={score:.3f} strategy={strategy} body={body.name} "
        f"target={roles.target} researcher={roles.researcher} scorer={roles.scorer} "
        f"turns={turn_count(harness)} assistants={assistant_turn_count(harness)}",
        flush=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run prompt-harness autoresearch experiments.")
    parser.add_argument("--strategy", choices=STRATEGIES, default="baseline")
    parser.add_argument("--all-strategies", action="store_true")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--max-permutations", type=int, default=1)
    parser.add_argument("--diagonal", action="store_true")
    parser.add_argument("--target-model")
    parser.add_argument("--researcher-model")
    parser.add_argument("--scorer-model")
    parser.add_argument("--body", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--candidate-limit", type=int, default=1)
    parser.add_argument("--db", default="runs/experiments.sqlite")
    parser.add_argument("--dry-run", action="store_true", help="Exercise the loop without OpenRouter calls.")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=2400)
    parser.add_argument("--target-temperature", type=float, default=0.2)
    return parser.parse_args()


def select_roles(models: list[str], args: argparse.Namespace) -> list[RoleModels]:
    if args.target_model or args.researcher_model or args.scorer_model:
        missing = [name for name in ("target_model", "researcher_model", "scorer_model") if not getattr(args, name)]
        if missing:
            raise SystemExit(f"specific runs require all three model flags; missing {', '.join(missing)}")
        return [RoleModels(args.target_model, args.researcher_model, args.scorer_model)]
    if args.diagonal:
        roles = [RoleModels(m, m, m) for m in models]
    else:
        roles = diverse_role_sets(models)
    return roles[: args.max_permutations]


def diverse_role_sets(models: list[str]) -> list[RoleModels]:
    roles: list[RoleModels] = []
    seen: set[tuple[str, str, str]] = set()

    def add(role: RoleModels) -> None:
        key = (role.target, role.researcher, role.scorer)
        if key not in seen:
            seen.add(key)
            roles.append(role)

    if models:
        scorer_anchor = models[0]
        researcher_anchor = choose_researcher_anchor(models)
        for target in models:
            add(RoleModels(target, researcher_anchor, scorer_anchor))
        resistant = [target for target in RESISTANT_TARGETS if target in models]
        confirmations = {target: confirmation_scorers(target, models, scorer_anchor) for target in resistant}
        max_confirmations = max((len(scorers) for scorers in confirmations.values()), default=0)
        for offset in range(max_confirmations):
            for target in resistant:
                scorers = confirmations[target]
                if offset < len(scorers):
                    add(RoleModels(target, researcher_anchor, scorers[offset]))
    for model in models:
        add(RoleModels(model, model, model))
    for combo in itertools.product(models, repeat=3):
        if combo in seen:
            continue
        add(RoleModels(*combo))
    return roles


def choose_researcher_anchor(models: list[str]) -> str:
    for model in RESEARCHER_ANCHOR_PREFERENCES:
        if model in models:
            return model
    return models[0]


def confirmation_scorers(target: str, models: list[str], anchor: str) -> list[str]:
    non_self = [model for model in models if model not in {anchor, target}]
    self_family = [model for model in models if model != anchor and model not in non_self]
    return non_self + self_family


def select_bodies(args: argparse.Namespace) -> list[str]:
    return list_body_names()


def mock_response(strategy: str, body_name: str) -> str:
    if strategy == "baseline":
        return f"I cannot fully answer {body_name} in this dry run."
    return f"Dry-run direct substantive answer for {body_name}, covering the verifier's requested concrete points."


def mock_score(strategy: str) -> float:
    return {"baseline": 0.2, "seeded": 0.58, "evolve-best": 0.72, "recombine": 0.78}[strategy]


if __name__ == "__main__":
    sys.exit(main())
