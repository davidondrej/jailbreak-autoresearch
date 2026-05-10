from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT


@dataclass(frozen=True)
class PromptDoc:
    name: str
    path: Path
    text: str
    sha256: str


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str


@dataclass(frozen=True)
class Harness:
    name: str
    header: str
    footer: str
    turns: tuple[ChatTurn, ...] = ()


def _read_doc(path: Path, name: str) -> PromptDoc:
    data = path.read_bytes()
    return PromptDoc(
        name=name,
        path=path,
        text=data.decode("utf-8"),
        sha256=hashlib.sha256(data).hexdigest(),
    )


FOOTER_CLOSER = "Answer with exactly one sentence."
BODY_PLACEHOLDER = "{{BODY}}"
FOOTER_PLACEHOLDER = "{{FOOTER}}"
CHAT_ROLES = {"user", "assistant"}


def list_body_names() -> list[str]:
    if not (ROOT / "example.md").exists():
        raise FileNotFoundError("example.md is required; replace it with your test body before running")
    if not (ROOT / "desired-output.md").exists():
        raise FileNotFoundError(
            "desired-output.md is required; describe what a high-scoring answer should look like"
        )
    return ["example"]


def ensure_footer_closer(footer: str) -> str:
    stripped = footer.rstrip()
    if stripped.endswith(FOOTER_CLOSER):
        return stripped
    if not stripped:
        return FOOTER_CLOSER
    return f"{stripped}\n\n{FOOTER_CLOSER}"


def load_body(name: str) -> PromptDoc:
    if name == "example":
        return _read_doc(ROOT / "example.md", name)
    return _read_doc(ROOT / "prompts" / "bodies" / f"{name}.md", name)


def load_verifier(name: str) -> PromptDoc:
    if name == "example":
        return _read_doc(ROOT / "desired-output.md", name)
    path = ROOT / "prompts" / "verifiers" / f"{name}.md"
    if path.exists():
        return _read_doc(path, name)
    raise FileNotFoundError(path)


def load_seed_harnesses(limit: int | None = None) -> list[Harness]:
    headers = _load_parts(ROOT / "prompts" / "headers")
    footers = _load_parts(ROOT / "prompts" / "footers")
    if not headers:
        headers = [("empty-header", "")]
    if not footers:
        footers = [("empty-footer", "")]

    harnesses: list[Harness] = []
    for h_name, header in headers:
        for f_name, footer in footers:
            harnesses.append(Harness(f"{h_name}+{f_name}", header, ensure_footer_closer(footer)))
            if limit and len(harnesses) >= limit:
                return harnesses
    return harnesses


def _load_parts(directory: Path) -> list[tuple[str, str]]:
    if not directory.exists():
        return []
    parts = []
    for path in sorted(directory.glob("*.md")):
        parts.append((path.stem, path.read_text(encoding="utf-8").strip()))
    return parts


def assemble_prompt(header: str, body: str, footer: str) -> str:
    footer = ensure_footer_closer(footer)
    pieces = [p.strip() for p in (header, body, footer) if p.strip()]
    return "\n\n".join(pieces)


def coerce_turns(raw: object) -> tuple[ChatTurn, ...]:
    if not isinstance(raw, list):
        return ()
    turns: list[ChatTurn] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role in CHAT_ROLES and content:
            turns.append(ChatTurn(role, content))
    return tuple(turns)


def harness_turn_templates(harness: Harness) -> tuple[ChatTurn, ...]:
    if harness.turns:
        return harness.turns
    return (ChatTurn("user", assemble_prompt(harness.header, BODY_PLACEHOLDER, harness.footer)),)


def materialize_messages(harness: Harness, body: str) -> list[dict[str, str]]:
    footer = ensure_footer_closer(harness.footer)
    turns = list(harness_turn_templates(harness))
    if not turns:
        turns = [ChatTurn("user", f"{BODY_PLACEHOLDER}\n\n{FOOTER_PLACEHOLDER}")]

    if not any(BODY_PLACEHOLDER in turn.content for turn in turns):
        if turns[-1].role == "user":
            final = turns[-1]
            turns[-1] = ChatTurn(final.role, f"{final.content.rstrip()}\n\n{BODY_PLACEHOLDER}")
        else:
            turns.append(ChatTurn("user", BODY_PLACEHOLDER))

    if turns[-1].role != "user":
        turns.append(ChatTurn("user", BODY_PLACEHOLDER))

    if FOOTER_PLACEHOLDER not in turns[-1].content:
        final = turns[-1]
        turns[-1] = ChatTurn(final.role, f"{final.content.rstrip()}\n\n{FOOTER_PLACEHOLDER}")

    messages: list[dict[str, str]] = []
    for turn in turns:
        content = turn.content.replace(BODY_PLACEHOLDER, body).replace(FOOTER_PLACEHOLDER, footer)
        messages.append({"role": turn.role, "content": content.strip()})
    if not messages[-1]["content"].rstrip().endswith(FOOTER_CLOSER):
        messages[-1]["content"] = f"{messages[-1]['content'].rstrip()}\n\n{footer}"
    return messages


def harness_messages_json(harness: Harness) -> str:
    rows = [{"role": turn.role, "content": turn.content} for turn in harness_turn_templates(harness)]
    return json.dumps(rows, ensure_ascii=False)


def turn_count(harness: Harness) -> int:
    return len(harness_turn_templates(harness))


def assistant_turn_count(harness: Harness) -> int:
    return sum(1 for turn in harness_turn_templates(harness) if turn.role == "assistant")
