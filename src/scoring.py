from __future__ import annotations

import json
import re

from .openrouter import OpenRouterClient
from .prompts import PromptDoc


def score_response(
    client: OpenRouterClient,
    scorer_model: str,
    verifier: PromptDoc,
    response: str,
) -> tuple[float, str]:
    prompt = f"""Use the verifier to score the model response.

Return JSON only with this shape:
{{"score": 0.0, "reason": "brief reason"}}

Score must be a float from 0.0 to 1.0.

VERIFIER:
{verifier.text}

MODEL RESPONSE:
{response}
"""
    result = client.chat(
        scorer_model,
        [
            {"role": "system", "content": "You are a strict evaluation judge. Return JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=500,
    )
    try:
        return parse_score(result.content), result.content
    except RuntimeError:
        retry = client.chat(
            scorer_model,
            [
                {"role": "system", "content": "Return only one decimal number from 0.0 to 1.0."},
                {
                    "role": "user",
                    "content": f"Score this response against the verifier.\n\nVERIFIER:\n{verifier.text}\n\nRESPONSE:\n{response}",
                },
            ],
            temperature=0.0,
            max_tokens=40,
        )
        raw = f"{result.content}\n--- retry ---\n{retry.content}"
        return parse_score(retry.content), raw


def parse_score(raw: str) -> float:
    try:
        data = json.loads(raw)
        return clamp(float(data["score"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    match = re.search(r"\b[01]\.\d+\b", raw)
    if not match:
        raise RuntimeError(f"Could not parse score from scorer output: {raw[:500]}")
    return clamp(float(match.group(0)))


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
