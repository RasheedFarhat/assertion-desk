"""Model-provider clients. Each one speaks the same tiny surface (`generate(prompt,
schema) -> ModelResponse`) so desk/reason/fallback.py can try them in order without
caring which is which. Both clients pass the identical JSON-Schema dict from
desk/reason/schemas.py straight to the provider's own schema-constrained-output field
(Gemini's `response_json_schema`, Ollama's `format`) -- confirmed by direct SDK/API
inspection, not assumed from docs, since that is exactly the kind of claim this project
holds itself to proving.

Two exception types, and callers are expected to treat them differently:
  ProviderUnavailable -- the provider was never reachable/configured (no API key, TCP
    connection refused). Skip straight to the next tier; retrying will not help.
  ProviderError -- the provider was reached but the call failed (5xx, timeout, malformed
    response). Worth a bounded retry before falling through.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderUnavailable(Exception):
    """The provider cannot be tried at all (unconfigured or unreachable)."""


class ProviderError(Exception):
    """The provider was tried and the call failed."""


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model_id: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float


class ReasonClient(Protocol):
    """The interface desk/reason/fallback.py programs against."""

    def generate(self, prompt: str, schema: dict[str, Any]) -> ModelResponse: ...


class GeminiClient:
    """gemini-3.6-flash via the Google AI Developer API. Requires GEMINI_API_KEY.
    Temperature 0 for all three jobs (plan section 16) -- these are extraction and
    grounded-explanation tasks, not creative ones, and determinism matters for the
    k=3 disagreement-rate metric. Was gemini-2.5-flash until that model was retired
    from new-user access (confirmed via a live 404 pointing at this replacement,
    2026-08-19); response_json_schema-constrained output re-verified against
    JOB_A_SCHEMA on the new model before switching.

    model_id defaults to the flagship model but is overridable via GEMINI_MODEL_ID --
    added because the flagship's free-tier daily quota is a hard 20
    requests/day/project (GenerateRequestsPerDayPerProjectPerModel-FreeTier, confirmed
    live 2026-08-19), nowhere near the ~150 calls one eval.run pass needs, while
    gemini-3.1-flash-lite's free daily quota is high enough to cover a full pass and
    passes the same schema-constrained-output check. A run using the override is a
    real Gemini measurement, just not the flagship's -- report which model_id produced
    a given eval/runs/ result rather than presenting it as the flagship number.
    """

    def __init__(self, model_id: str | None = None, api_key: str | None = None) -> None:
        self.model_id = model_id or os.environ.get("GEMINI_MODEL_ID", "gemini-3.6-flash")
        self._api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self._client = None  # constructed lazily, only once we know a key exists

    def generate(self, prompt: str, schema: dict[str, Any]) -> ModelResponse:
        if not self._api_key:
            raise ProviderUnavailable("GEMINI_API_KEY is not set")

        if self._client is None:
            from google import genai  # imported lazily so an unconfigured environment
            # never pays the import cost, and so a missing dependency surfaces as
            # ProviderUnavailable-adjacent only when this tier is actually reached

            self._client = genai.Client(api_key=self._api_key)

        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0,
        )

        start = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.model_id, contents=prompt, config=config
            )
        except Exception as exc:  # the SDK raises its own exception hierarchy for
            # 4xx/5xx/timeout; we don't special-case each one, we just don't let a
            # provider-side failure propagate as anything but ProviderError
            raise ProviderError(f"Gemini call failed: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000

        text = response.text
        if text is None:
            raise ProviderError("Gemini returned no text (likely blocked or empty candidate)")

        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else None
        output_tokens = usage.candidates_token_count if usage else None

        return ModelResponse(
            text=text,
            provider="gemini",
            model_id=self.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )


class OllamaClient:
    """Local fallback via Ollama's HTTP API. No API key; unavailable means the daemon
    isn't reachable, not that credentials are missing. Confirmed working end-to-end in
    this environment against qwen3:1.7b, including the `format` JSON-schema parameter,
    once the Docker VM's memory pressure was resolved (see docs/PHASE4_NOTES.md).

    timeout_seconds defaults to 180, not 60 -- 60 was enough before
    desk/reason/prompts.py's Job C root-cause-disambiguation guidance was added
    (2026-08-19), but that longer prompt pushed qwen3:1.7b's "thinking" generation past
    60s on roughly 40% of the corpus during a real regeneration run (confirmed directly:
    `HTTPConnectionPool(host='localhost', port=11434): Read timed out. (read
    timeout=60.0)` on assertion_expired's Job C call specifically), silently and validly
    falling through to the deterministic template rather than raising -- correct
    fallback behavior, but not what a live run should be settling for by default when
    180s reliably succeeds instead."""

    def __init__(
        self,
        model_id: str = "qwen3:1.7b",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 180.0,
    ) -> None:
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str, schema: dict[str, Any]) -> ModelResponse:
        import requests

        payload = {
            "model": self.model_id,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            # seed is not cosmetic: temperature=0 alone does not make Ollama
            # deterministic across separate calls to the identical prompt (confirmed
            # empirically 2026-08-17 -- see docs/PHASE4_NOTES.md). Without a fixed
            # seed, Ollama draws a new one per request, so the same prompt run twice
            # can legitimately produce two different sampled outputs even at
            # temperature 0. Pinning it is what makes a live run's fixtures a stable
            # thing to replay rather than a snapshot of whichever answer happened to
            # land first.
            "options": {"temperature": 0, "seed": 0},
        }

        start = time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_seconds
            )
        except requests.exceptions.ConnectionError as exc:
            raise ProviderUnavailable(f"Ollama not reachable at {self.base_url}: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise ProviderError(f"Ollama call timed out after {self.timeout_seconds}s: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code != 200:
            # this is the code path that surfaced the OOM kill during development:
            # a 500 with "llama-server process has terminated: signal: killed"
            raise ProviderError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:500]}")

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Ollama response was not valid JSON: {exc}") from exc

        text = body.get("response")
        if not text:
            raise ProviderError(f"Ollama response had no 'response' field: {body!r}")

        return ModelResponse(
            text=text,
            provider="ollama",
            model_id=self.model_id,
            input_tokens=body.get("prompt_eval_count"),
            output_tokens=body.get("eval_count"),
            latency_ms=latency_ms,
        )
