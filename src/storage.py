from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from .config import ROOT
from .prompts import FOOTER_CLOSER


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  run_id TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 0,
  strategy TEXT NOT NULL,
  candidate_name TEXT NOT NULL,
  body_name TEXT NOT NULL,
  body_sha256 TEXT NOT NULL,
  target_model TEXT NOT NULL,
  researcher_model TEXT NOT NULL,
  scorer_model TEXT NOT NULL,
  max_tokens INTEGER,
  target_temperature REAL,
  timeout INTEGER,
  header TEXT NOT NULL,
  footer TEXT NOT NULL,
  messages_json TEXT NOT NULL DEFAULT '[]',
  turn_count INTEGER NOT NULL DEFAULT 1,
  assistant_turn_count INTEGER NOT NULL DEFAULT 0,
  response TEXT NOT NULL,
  score REAL NOT NULL,
  scorer_raw TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_experiment_lookup
ON experiments(body_name, target_model, strategy, dry_run, score DESC);

CREATE TABLE IF NOT EXISTS fragments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source_experiment_id INTEGER NOT NULL,
  body_name TEXT NOT NULL,
  target_model TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('header', 'footer')),
  text TEXT NOT NULL,
  score REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fragments_lookup
ON fragments(body_name, target_model, kind, score DESC);
"""


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or ROOT / "runs" / "experiments.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(experiments)")}
        for name, ddl in {
            "max_tokens": "ALTER TABLE experiments ADD COLUMN max_tokens INTEGER",
            "target_temperature": "ALTER TABLE experiments ADD COLUMN target_temperature REAL",
            "timeout": "ALTER TABLE experiments ADD COLUMN timeout INTEGER",
            "messages_json": "ALTER TABLE experiments ADD COLUMN messages_json TEXT NOT NULL DEFAULT '[]'",
            "turn_count": "ALTER TABLE experiments ADD COLUMN turn_count INTEGER NOT NULL DEFAULT 1",
            "assistant_turn_count": (
                "ALTER TABLE experiments ADD COLUMN assistant_turn_count INTEGER NOT NULL DEFAULT 0"
            ),
        }.items():
            if name not in cols:
                self.conn.execute(ddl)

    def insert_experiment(self, row: dict[str, Any]) -> int:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self.conn.execute(
            f"INSERT INTO experiments ({cols}) VALUES ({marks})",
            list(row.values()),
        )
        exp_id = int(cur.lastrowid)
        self._insert_fragments(exp_id, row)
        self.conn.commit()
        return exp_id

    def best_experiments(
        self,
        body_name: str,
        target_model: str | None,
        limit: int = 5,
        dry_run: bool = False,
    ) -> list[sqlite3.Row]:
        if target_model is None:
            return self.conn.execute(
                """
                SELECT * FROM experiments
                WHERE body_name = ? AND dry_run = ? AND scorer_raw NOT LIKE '{"error":%'
                ORDER BY score DESC, id DESC
                LIMIT ?
                """,
                (body_name, int(dry_run), limit),
            ).fetchall()
        return self.conn.execute(
            """
            SELECT * FROM experiments
            WHERE body_name = ? AND target_model = ? AND dry_run = ?
              AND scorer_raw NOT LIKE '{"error":%'
            ORDER BY score DESC, id DESC
            LIMIT ?
            """,
            (body_name, target_model, int(dry_run), limit),
        ).fetchall()

    def top_fragments(
        self,
        body_name: str,
        target_model: str | None,
        kind: str,
        limit: int = 8,
    ) -> list[sqlite3.Row]:
        if target_model is None:
            return self.conn.execute(
                """
                SELECT text, MAX(score) AS score FROM fragments
                WHERE body_name = ? AND kind = ?
                GROUP BY text
                ORDER BY score DESC
                LIMIT ?
                """,
                (body_name, kind, limit),
            ).fetchall()
        return self.conn.execute(
            """
            SELECT text, MAX(score) AS score FROM fragments
            WHERE body_name = ? AND target_model = ? AND kind = ?
            GROUP BY text
            ORDER BY score DESC
            LIMIT ?
            """,
            (body_name, target_model, kind, limit),
        ).fetchall()

    def experiment_count(self, body_name: str, target_model: str, strategy: str) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM experiments
            WHERE body_name = ? AND target_model = ? AND strategy = ?
              AND dry_run = 0
            """,
            (body_name, target_model, strategy),
        ).fetchone()
        return int(row["n"])

    def _insert_fragments(self, exp_id: int, row: dict[str, Any]) -> None:
        if row["strategy"] == "baseline" or float(row["score"]) < 0.4:
            return
        for kind in ("header", "footer"):
            for text in split_fragments(row[kind]):
                self.conn.execute(
                    """
                    INSERT INTO fragments
                    (source_experiment_id, body_name, target_model, kind, text, score)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (exp_id, row["body_name"], row["target_model"], kind, text, row["score"]),
                )


def split_fragments(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|;\s+|\n+", cleaned)
    seen: set[str] = set()
    out: list[str] = []
    for chunk in chunks:
        item = chunk.strip()
        if item == FOOTER_CLOSER:
            continue
        if 24 <= len(item) <= 500 and item not in seen:
            seen.add(item)
            out.append(item)
    return out
