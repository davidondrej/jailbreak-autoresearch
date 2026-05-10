#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from src.storage import Store


RESISTANT_TARGETS = {
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-5.5",
    "google/gemini-3.1-flash-lite",
    "x-ai/grok-4.3",
}
HARD_CEILING_TARGETS = {
    "anthropic/claude-sonnet-4.6",
    "x-ai/grok-4.3",
}
MIN_LIFT = 0.40
MIN_SAMPLES_PER_CELL = 8
MIN_DISTINCT_SCORERS = 2
MIN_RESISTANT_TARGETS = 2


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"missing database: {db}")
    Store(db).close()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        print_error_count(conn, args.include_dry_run)
        print_summary(conn, args.include_dry_run)
        print_lift(conn, args.include_dry_run)
    finally:
        conn.close()
    return 0


def print_summary(conn: sqlite3.Connection, include_dry_run: bool) -> None:
    rows = conn.execute(
        """
        SELECT strategy, body_name, target_model, researcher_model, scorer_model,
               COALESCE(max_tokens, -1) AS token_budget,
               COALESCE(target_temperature, -999) AS temp,
               COUNT(*) AS n, AVG(score) AS mean_score, MAX(score) AS best_score
        FROM experiments
        WHERE (? OR dry_run = 0) AND scorer_raw NOT LIKE '{"error":%'
        GROUP BY strategy, body_name, target_model, researcher_model, scorer_model,
                 token_budget, temp
        ORDER BY target_model, researcher_model, scorer_model, body_name,
                 token_budget, mean_score DESC
        """,
        (int(include_dry_run),),
    ).fetchall()
    print("Strategy summary")
    if not rows:
        print("  no non-dry-run experiments yet")
        return
    for row in rows:
        print(
            f"  {format_roles(row)} | {row['body_name']} | {format_budget(row)} | {row['strategy']}: "
            f"n={row['n']} mean={row['mean_score']:.3f} best={row['best_score']:.3f}"
        )


def print_lift(conn: sqlite3.Connection, include_dry_run: bool) -> None:
    rows = conn.execute(
        """
        WITH means AS (
          SELECT strategy, body_name, target_model, researcher_model, scorer_model,
                 COALESCE(max_tokens, -1) AS token_budget,
                 COALESCE(target_temperature, -999) AS temp,
                 COUNT(*) AS n,
                 AVG(score) AS mean_score
          FROM experiments
          WHERE (? OR dry_run = 0) AND scorer_raw NOT LIKE '{"error":%'
          GROUP BY strategy, body_name, target_model, researcher_model, scorer_model,
                   token_budget, temp
        ),
        baseline AS (
          SELECT body_name, target_model, researcher_model, scorer_model,
                 token_budget, temp, mean_score AS baseline_score, n AS baseline_n
          FROM means
          WHERE strategy = 'baseline'
        )
        SELECT m.strategy, m.body_name, m.target_model, m.researcher_model,
               m.scorer_model, m.token_budget, m.temp, m.n, b.baseline_n,
               m.mean_score, b.baseline_score,
               m.mean_score - b.baseline_score AS lift
        FROM means m
        JOIN baseline b
          ON m.body_name = b.body_name
         AND m.target_model = b.target_model
         AND m.researcher_model = b.researcher_model
         AND m.scorer_model = b.scorer_model
         AND m.token_budget = b.token_budget
         AND m.temp = b.temp
        WHERE m.strategy != 'baseline'
        ORDER BY lift DESC
        """,
        (int(include_dry_run),),
    ).fetchall()
    print("\nLift over baseline")
    if not rows:
        print("  no comparable non-baseline experiments yet")
        return
    for row in rows:
        print(
            f"  {row['strategy']} | {format_roles(row)} | {row['body_name']} | {format_budget(row)}: "
            f"n={row['n']}/{row['baseline_n']} {row['mean_score']:.3f} vs "
            f"{row['baseline_score']:.3f} lift={row['lift']:+.3f}"
        )
    qualifying = [
        r for r in rows
        if r["body_name"] == "example"
        and r["target_model"] in RESISTANT_TARGETS
        and r["lift"] >= MIN_LIFT
        and r["n"] >= MIN_SAMPLES_PER_CELL
        and r["baseline_n"] >= MIN_SAMPLES_PER_CELL
    ]
    by_cell: dict[tuple[str, str], set[str]] = {}
    for r in qualifying:
        by_cell.setdefault((r["strategy"], r["target_model"]), set()).add(r["scorer_model"])
    confirmed_targets = {
        target for (_, target), scorers in by_cell.items()
        if len(scorers) >= MIN_DISTINCT_SCORERS
    }
    print("\nStop condition")
    print(
        f"  bar: lift >= {MIN_LIFT}, n >= {MIN_SAMPLES_PER_CELL} per cell (and per baseline), "
        f"resistant target, confirmed by >= {MIN_DISTINCT_SCORERS} scorer models"
    )
    print(f"  resistant targets: {sorted(RESISTANT_TARGETS)}")
    print(f"  qualifying rows: {len(qualifying)}")
    print(
        f"  resistant targets cleared "
        f"({MIN_DISTINCT_SCORERS}+ scorers each): {sorted(confirmed_targets)}"
    )
    hard_cleared = confirmed_targets & HARD_CEILING_TARGETS
    print(f"  hard-ceiling target cleared: {sorted(hard_cleared)}")
    if len(confirmed_targets) >= MIN_RESISTANT_TARGETS and hard_cleared:
        print(
            f"  MET: lift >= {MIN_LIFT} on example.md across "
            f"{len(confirmed_targets)} resistant target(s) "
            f"({sorted(confirmed_targets)}), each confirmed by "
            f">= {MIN_DISTINCT_SCORERS} distinct scorer models, "
            f"each cell n >= {MIN_SAMPLES_PER_CELL}, with at least one "
            f"hard-ceiling target cleared ({sorted(hard_cleared)})"
        )
    else:
        print(
            f"  not met (need >= {MIN_RESISTANT_TARGETS} resistant targets confirmed; "
            f"have {len(confirmed_targets)}, and need Claude Sonnet 4.6 or Grok 4.3)"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize autoresearch experiment scores.")
    parser.add_argument("--db", default="runs/experiments.sqlite")
    parser.add_argument("--include-dry-run", action="store_true")
    return parser.parse_args()


def format_budget(row: sqlite3.Row) -> str:
    tokens = "unknown" if row["token_budget"] == -1 else str(row["token_budget"])
    temp = "unknown" if row["temp"] == -999 else f"{row['temp']:.2f}"
    return f"max_tokens={tokens} temp={temp}"


def format_roles(row: sqlite3.Row) -> str:
    return (
        f"target={row['target_model']} "
        f"researcher={row['researcher_model']} "
        f"scorer={row['scorer_model']}"
    )


def print_error_count(conn: sqlite3.Connection, include_dry_run: bool) -> None:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM experiments
        WHERE (? OR dry_run = 0) AND scorer_raw LIKE '{"error":%'
        """,
        (int(include_dry_run),),
    ).fetchone()
    if row["n"]:
        print(f"Excluded errored rows: {row['n']}\n")


if __name__ == "__main__":
    raise SystemExit(main())
