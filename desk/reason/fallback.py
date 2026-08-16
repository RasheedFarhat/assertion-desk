"""Tier orchestration: fixture-replay -> each configured client in order (with a
bounded retry on transient failures) -> deterministic-only.

This is T7 from the plan's threat model ("model unavailable, rate-limited, or
degraded"): the system must still produce a correct verdict when every model tier is
exhausted, just a less well-written one. This module decides *which tier answered*; it
deliberately does not know how to render a deterministic-only response itself -- that
template logic lives in desk/reason/jobs.py, next to the prompts it's a fallback for,
so this file stays a pure dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from desk.reason.client import ModelResponse, ProviderError, ProviderUnavailable, ReasonClient
from desk.reason.fixtures import FixtureCache
from desk.reason.schemas import SCHEMA_VERSION


class ReplayMiss(Exception):
    """Raised in replay_only mode when no fixture covers this exact
    (prompt, model_id, schema_version). Loud on purpose: replay mode's entire point is
    that it never touches the network, so a miss must stop the run, not silently fall
    through to a live call that would break `make eval-replay`'s $0/no-key guarantee."""


@dataclass
class TierAttempt:
    tier: str  # "fixture" | a client's model_id | "deterministic"
    provider: str | None
    ok: bool
    detail: str | None = None


@dataclass
class TieredResult:
    tier_used: str  # "fixture" | a provider name | "deterministic"
    response: ModelResponse | None  # None only when tier_used == "deterministic"
    fixture_hit: bool
    attempts: list[TierAttempt] = field(default_factory=list)


def run_with_fallback(
    prompt: str,
    schema: dict[str, Any],
    *,
    clients: list[ReasonClient],
    fixtures: FixtureCache,
    schema_version: str = SCHEMA_VERSION,
    replay_only: bool = False,
    max_retries_per_client: int = 1,
    record_fixtures: bool = True,
) -> TieredResult:
    attempts: list[TierAttempt] = []

    # Tier 0: fixture replay, checked in the same priority order clients would be
    # tried live (a fixture for a higher-priority client wins over a lower one), so
    # replay results match what a live run would have preferred.
    for client in clients:
        model_id = getattr(client, "model_id", None)
        if model_id is None:
            continue
        cached = fixtures.get(prompt, model_id, schema_version)
        if cached is not None:
            attempts.append(TierAttempt(tier="fixture", provider=cached.provider, ok=True))
            return TieredResult(
                tier_used="fixture", response=cached, fixture_hit=True, attempts=attempts
            )

    if replay_only:
        tried = [getattr(c, "model_id", c.__class__.__name__) for c in clients]
        raise ReplayMiss(f"replay_only=True and no fixture found for any of {tried}")

    # Tiers 1..N: each configured client in order. ProviderUnavailable means "don't
    # bother retrying this one, move on"; ProviderError gets a bounded retry first,
    # since that class covers transient failures (a 5xx, a timeout, an OOM kill).
    for client in clients:
        provider_name = getattr(client, "model_id", client.__class__.__name__)
        for attempt_num in range(1, max(1, max_retries_per_client) + 1):
            try:
                response = client.generate(prompt, schema)
            except ProviderUnavailable as exc:
                attempts.append(TierAttempt(tier=provider_name, provider=None, ok=False, detail=str(exc)))
                break  # unreachable/unconfigured; retrying changes nothing
            except ProviderError as exc:
                attempts.append(
                    TierAttempt(
                        tier=provider_name,
                        provider=None,
                        ok=False,
                        detail=f"attempt {attempt_num}/{max_retries_per_client}: {exc}",
                    )
                )
                continue  # transient; try again up to the retry budget
            else:
                attempts.append(TierAttempt(tier=provider_name, provider=response.provider, ok=True))
                if record_fixtures:
                    fixtures.put(prompt, response.model_id, response, schema_version)
                return TieredResult(
                    tier_used=response.provider, response=response, fixture_hit=False, attempts=attempts
                )
        # this client's retry budget is exhausted (or it was unavailable); fall
        # through to the next configured client

    # Every tier exhausted. The caller renders a deterministic template; this function
    # only reports that it had to.
    return TieredResult(tier_used="deterministic", response=None, fixture_hit=False, attempts=attempts)
