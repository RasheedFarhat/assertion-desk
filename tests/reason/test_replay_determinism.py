"""Phase 4 exit criteria (plan section 27): a replay-determinism test. `make
eval-replay`'s entire promise is that a stranger can clone the repo, run it with no
API key and no network, and reproduce the exact published numbers (plan section 23,
verification step 5) -- this file is the test that promise actually holds, by running
eval.run.run_corpus(replay_only=True) twice against the same real committed fixtures
and asserting byte-identical output.

Case selection is deliberate, not "the first few in the manifest," and it is derived
from the real fixture cache rather than assumed. `fixtures/` is written by whatever
live/replay runs have happened to execute in this environment (including a slow
background full-corpus run), so which cases are fully covered changes over time and
must not be hand-picked from memory of an old aggregate summary -- an earlier attempt
at this file did exactly that (guessed clock_skew and duplicate_role_attributes from a
remembered tier_usage total) and it was wrong: neither case's Job A prompt actually had
a matching fixture. The three case IDs below were instead found by directly probing
the real fixture cache with `eval.run.run_corpus(..., replay_only=True)` over every
case in the manifest and keeping only the ones where every invoked job's `tier_used`
came back `"fixture"`. If `fixtures/` grows or changes, re-run that probe rather than
editing this list by hand.

Asserting determinism only matters on cases that actually reach the fixture tier for
every job -- a case where the model tier is skipped in favor of the deterministic
template would make two replay_only runs trivially agree with each other for the wrong
reason (the deterministic template has no randomness of its own), which is exactly
what the tier_used assertion at the bottom of the first test guards against.
test_fallback.py already covers the ReplayMiss-on-a-genuine-miss behavior directly, so
this file does not need to exercise that path too.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from desk.reason.client import ProviderError
from desk.reason.fixtures import FixtureCache
from eval.run import build_clients, run_corpus

FULLY_FIXTURE_COVERED_CASE_IDS = [
    "assertion_expired",
    "assertion_expired__adv_s4_obfuscated",
    "broken_signature__non_native",
]


def _instrument_and_forbid_live_calls(clients):
    """Wraps every client's generate() to record any invocation and then raise --
    replay_only mode's fixture-only contract means these must never be reached, so a
    call here is exactly the regression this test exists to catch. Returns the
    clients plus a shared call log, checked directly rather than inferred from
    run_corpus's own per-case exception isolation (which would otherwise swallow a
    raised ProviderError as an ordinary case-level error and hide the regression)."""
    call_log: list[str] = []
    for client in clients:
        name = client.__class__.__name__

        def _refuse(prompt, schema, _name=name):
            call_log.append(_name)
            raise ProviderError(f"{_name}.generate() must never be called in replay_only mode")

        client.generate = _refuse
    return clients, call_log


@pytest.fixture
def real_fixtures():
    """The real, committed fixtures/ directory -- not a tmp_path copy. The point of
    this test is that *this repo's* replay guarantee holds, which means exercising the
    exact fixture cache `make eval-replay` reads."""
    return FixtureCache()


def test_replay_only_run_is_byte_identical_across_two_runs(real_fixtures):
    clients_run_1, call_log_1 = _instrument_and_forbid_live_calls(build_clients())
    clients_run_2, call_log_2 = _instrument_and_forbid_live_calls(build_clients())

    records_1 = run_corpus(
        FULLY_FIXTURE_COVERED_CASE_IDS, clients=clients_run_1, fixtures=real_fixtures, replay_only=True
    )
    records_2 = run_corpus(
        FULLY_FIXTURE_COVERED_CASE_IDS, clients=clients_run_2, fixtures=real_fixtures, replay_only=True
    )
    assert call_log_1 == []
    assert call_log_2 == []

    assert len(records_1) == len(FULLY_FIXTURE_COVERED_CASE_IDS)
    as_json_1 = json.dumps([dataclasses.asdict(r) for r in records_1], indent=2, sort_keys=True)
    as_json_2 = json.dumps([dataclasses.asdict(r) for r in records_2], indent=2, sort_keys=True)
    assert as_json_1 == as_json_2

    # And the substance, not just self-agreement: every case actually reached a real
    # tier (fixture), never fell through to deterministic -- otherwise two
    # deterministic renders would trivially agree with each other for the wrong reason.
    for record in records_1:
        for job in (record.job_a, record.job_b, record.job_c):
            if job is not None:
                assert job.tier_used == "fixture", (
                    f"{record.case_id}/{job.job}: expected a fixture-tier response, got "
                    f"{job.tier_used!r} -- this case no longer belongs in "
                    "FULLY_FIXTURE_COVERED_CASE_IDS, or fixtures/ has drifted"
                )


def test_replay_only_touches_no_client_generate_call(real_fixtures):
    """Belt-and-suspenders on top of the byte-identical assertion above: confirms the
    zero-network-calls guarantee directly via the call log, rather than only inferring
    it from tier_used being "fixture" everywhere."""
    clients, call_log = _instrument_and_forbid_live_calls(build_clients())
    records = run_corpus(FULLY_FIXTURE_COVERED_CASE_IDS, clients=clients, fixtures=real_fixtures, replay_only=True)
    assert call_log == []
    for record in records:
        assert record.verify_state != "error", record.error
        assert record.error is None
