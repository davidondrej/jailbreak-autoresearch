from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


API_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class ChatResult:
    content: str
    raw: dict


class OpenRouterClient:
    def __init__(self, api_key: str, timeout: int = 90, retries: int = 1) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1800,
    ) -> ChatResult:
        last_error: RuntimeError | None = None
        for attempt in range(self.retries + 1):
            raw = self._request(self._request_payload(model, messages, temperature, max_tokens))
            try:
                return ChatResult(content=extract_content(raw), raw=raw)
            except RuntimeError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2**attempt)
        assert last_error is not None
        raise last_error

    def _request_payload(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> urllib.request.Request:
        data = json.dumps(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        return urllib.request.Request(
            API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/davidondrej/jailbreak-autoresearch",
                "X-Title": "jailbreak-autoresearch",
            },
            method="POST",
        )

    def _request(self, req: urllib.request.Request) -> dict:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code < 500 and exc.code != 429:
                    raise RuntimeError(f"OpenRouter HTTP {exc.code}: {body[:1200]}") from exc
                last_error = RuntimeError(f"OpenRouter HTTP {exc.code}: {body[:1200]}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = RuntimeError(f"OpenRouter request failed: {exc}")
            if attempt < self.retries:
                time.sleep(2**attempt)
        assert last_error is not None
        raise last_error


def extract_content(raw: dict) -> str:
    try:
        message = raw["choices"][0]["message"]
        content = message.get("content")
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response: {raw}") from exc
    if isinstance(content, list):
        content = "".join(str(part.get("text", part)) for part in content)
    if content is None:
        content = message.get("reasoning")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"Unexpected OpenRouter message: {json.dumps(message)[:1200]}")
    return content
