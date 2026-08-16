"""Phase 4 exit criteria (plan section 27): a forced-failure chaos test for each
fallback tier. desk/reason/fallback.py:run_with_fallback is T7 from the threat model
("model unavailable, rate-limited, or degraded") -- this file forces every tier in the
cascade to fail on purpose and asserts the next tier is actually tried, using a
FakeClient scripted to fail or succeed on command rather than a real provider, so every
branch is reachable without a network call or an API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from desk.reason.client import ModelResponse, ProviderError, ProviderUnavailable
from desk.reason.fallback import ReplayMiss, run_with_fallback
from desk.reason.fixtures import FixtureCache

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@dataclass
class FakeClient:
    """Implements the same tiny surface as desk/reason/client.py's ReasonClient
    Protocol (model_id + generate(prompt, schema)), scripted to raise or return a
    queued sequence of outcomes so a test can force exactly the tier behavior it's
    checking without touching Gemini or Ollama."""

    model_id: str
    outcomes: list[Any]  # each entry is either an Exception instance to raise, or a ModelResponse to return
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def generate(self, prompt: str, schema: dict[str, Any]) -> ModelResponse:
        self.calls.append((prompt, schema))
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(provider: str, model_id: str, text: str = '{"ok": true}') -> ModelResponse:
    return ModelResponse(
        text=text, provider=provider, model_id=model_id, input_tokens=10, output_tokens=5, latency_ms=42.0
    )


# --------------------------------------------------------------------------------- #
# Tier 0: fixture replay wins over every live client, and no live call happens when it
# hits.
# --------------------------------------------------------------------------------- #


def test_fixture_hit_short_circuits_before_any_client_is_called(tmp_path):
    fixtures = FixtureCache(tmp_path)
    fixtures.put("prompt-1", "fake-model", _response("fake", "fake-model"))
    client = FakeClient(model_id="fake-model", outcomes=[AssertionError("must not be called")])

    result = run_with_fallback("prompt-1", SCHEMA, clients=[client], fixtures=fixtures)

    assert result.tier_used == "fixture"
    assert result.fixture_hit is True
    assert client.calls == []  # the whole point: a cached fixture never reaches generate()


def test_fixture_priority_matches_client_order(tmp_path):
    """A fixture recorded for a higher-priority client wins over one recorded for a
    lower-priority client, so replay results match what a live run would have
    preferred (module docstring)."""
    primary_client = FakeClient(model_id="primary", outcomes=[])
    secondary_client = FakeClient(model_id="secondary", outcomes=[])

    fixtures = FixtureCache(tmp_path)
    fixtures.put("prompt-1", "secondary", _response("fake", "secondary", '{"ok": false}'))
    fixtures.put("prompt-1", "primary", _response("fake", "primary", '{"ok": true}'))

    result = run_with_fallback(
        "prompt-1", SCHEMA, clients=[primary_client, secondary_client], fixtures=fixtures
    )
    assert result.tier_used == "fixture"
    assert result.response.model_id == "primary"


# --------------------------------------------------------------------------------- #
# Tier 1..N: live clients, tried in order.
# --------------------------------------------------------------------------------- #


def test_live_success_on_first_client_is_used_and_recorded_as_a_fixture(tmp_path):
    fixtures = FixtureCache(tmp_path)
    client = FakeClient(model_id="primary", outcomes=[_response("primary-provider", "primary")])

    result = run_with_fallback("prompt-2", SCHEMA, clients=[client], fixtures=fixtures)

    assert result.tier_used == "primary-provider"
    assert result.fixture_hit is False
    assert len(client.calls) == 1
    # recorded so a second call (or a later replay run) hits the fixture tier instead
    assert fixtures.get("prompt-2", "primary") is not None


def test_provider_unavailable_skips_straight_to_next_client_with_no_retry(tmp_path):
    """ProviderUnavailable means unreachable/unconfigured -- module docstring says
    retrying changes nothing, so it must not consume the retry budget before falling
    through."""
    fixtures = FixtureCache(tmp_path)
    unavailable = FakeClient(model_id="primary", outcomes=[ProviderUnavailable("no API key")])
    healthy = FakeClient(model_id="secondary", outcomes=[_response("secondary-provider", "secondary")])

    result = run_with_fallback(
        "prompt-3", SCHEMA, clients=[unavailable, healthy], fixtures=fixtures, max_retries_per_client=3
    )

    assert result.tier_used == "secondary-provider"
    assert len(unavailable.calls) == 1  # not retried
    assert len(healthy.calls) == 1


def test_provider_error_is_retried_up_to_the_budget_then_falls_through(tmp_path):
    """ProviderError covers transient failures (a 5xx, a timeout) and is worth a
    bounded retry before moving on."""
    fixtures = FixtureCache(tmp_path)
    flaky = FakeClient(
        model_id="primary",
        outcomes=[ProviderError("timeout"), ProviderError("timeout")],
    )
    healthy = FakeClient(model_id="secondary", outcomes=[_response("secondary-provider", "secondary")])

    result = run_with_fallback(
        "prompt-4", SCHEMA, clients=[flaky, healthy], fixtures=fixtures, max_retries_per_client=2
    )

    assert result.tier_used == "secondary-provider"
    assert len(flaky.calls) == 2  # both retries consumed
    assert len(healthy.calls) == 1
    assert all(not a.ok for a in result.attempts if a.tier == "primary")


def test_provider_error_recovers_within_the_retry_budget(tmp_path):
    """The mirror case: a client that fails once but succeeds on its second attempt
    must be used, not skipped -- the retry budget exists precisely for this."""
    fixtures = FixtureCache(tmp_path)
    recovers = FakeClient(
        model_id="primary",
        outcomes=[ProviderError("timeout"), _response("primary-provider", "primary")],
    )

    result = run_with_fallback("prompt-5", SCHEMA, clients=[recovers], fixtures=fixtures, max_retries_per_client=2)

    assert result.tier_used == "primary-provider"
    assert len(recovers.calls) == 2


def test_every_tier_exhausted_falls_to_deterministic(tmp_path):
    fixtures = FixtureCache(tmp_path)
    client_a = FakeClient(model_id="primary", outcomes=[ProviderError("down")])
    client_b = FakeClient(model_id="secondary", outcomes=[ProviderUnavailable("down")])

    result = run_with_fallback("prompt-6", SCHEMA, clients=[client_a, client_b], fixtures=fixtures)

    assert result.tier_used == "deterministic"
    assert result.response is None
    assert result.fixture_hit is False
    # nothing to replay later either -- deterministic tier never calls fixtures.put()
    assert fixtures.get("prompt-6", "primary") is None
    assert fixtures.get("prompt-6", "secondary") is None


def test_record_fixtures_false_does_not_persist_a_live_success(tmp_path):
    fixtures = FixtureCache(tmp_path)
    client = FakeClient(model_id="primary", outcomes=[_response("primary-provider", "primary")])

    result = run_with_fallback(
        "prompt-7", SCHEMA, clients=[client], fixtures=fixtures, record_fixtures=False
    )

    assert result.tier_used == "primary-provider"
    assert fixtures.get("prompt-7", "primary") is None


# --------------------------------------------------------------------------------- #
# replay_only=True: the network must never be touched, and a miss is loud, not silent
# (ReplayMiss's own docstring -- this is the contract `make eval-replay` depends on).
# --------------------------------------------------------------------------------- #


def test_replay_only_raises_on_a_miss_and_never_calls_the_client(tmp_path):
    fixtures = FixtureCache(tmp_path)
    client = FakeClient(model_id="primary", outcomes=[AssertionError("must not be called")])

    with pytest.raises(ReplayMiss):
        run_with_fallback("prompt-8", SCHEMA, clients=[client], fixtures=fixtures, replay_only=True)

    assert client.calls == []


def test_replay_only_still_hits_a_real_fixture(tmp_path):
    fixtures = FixtureCache(tmp_path)
    fixtures.put("prompt-9", "primary", _response("primary-provider", "primary"))
    client = FakeClient(model_id="primary", outcomes=[AssertionError("must not be called")])

    result = run_with_fallback("prompt-9", SCHEMA, clients=[client], fixtures=fixtures, replay_only=True)

    assert result.tier_used == "fixture"
    assert client.calls == []
