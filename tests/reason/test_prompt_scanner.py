"""First direct coverage of desk/reason/prompts.py's detect_instruction_shaped_spans.
Before this file, the scanner was only exercised indirectly (through run_job_a on real
narrative text), so a regression in the pattern list or a payload's own wording could
drift out of sync silently -- exactly the failure mode this repo's own 2026-08-23
finding was about (see docs/PHASE4_NOTES.md's update): the scanner existed, but was
never wired into two of the three places an attacker-controlled string can reach a
prompt from.

Parametrized over harness/adversarial.py's ALL_PAYLOADS rather than a hand-picked
sample, so a new payload added there is automatically checked here too.
"""

from __future__ import annotations

import pytest

from desk.reason.prompts import detect_instruction_shaped_spans
from harness.adversarial import ALL_PAYLOADS, InjectionPayload


@pytest.mark.parametrize("payload", ALL_PAYLOADS, ids=[p.payload_id for p in ALL_PAYLOADS])
def test_scanner_flags_every_payload_unless_it_declares_evasion(payload: InjectionPayload):
    signals = detect_instruction_shaped_spans(payload.span_excerpt)
    if payload.evades_detector:
        # The point of this flag is an honestly-labeled blind spot, not an assumption --
        # assert the scanner actually misses it, so a pattern-list change that
        # accidentally starts catching an "evading" payload is caught here rather than
        # silently making the flag a lie.
        assert signals == [], (
            f"{payload.payload_id} claims evades_detector=True but the scanner caught it "
            f"anyway ({signals!r}); either fix the flag or the payload no longer evades"
        )
    else:
        assert signals, (
            f"{payload.payload_id} claims evades_detector=False but "
            "detect_instruction_shaped_spans found nothing in its span_excerpt -- either "
            "the pattern list needs widening or the flag is wrong"
        )


def test_reaches_prompt_payloads_are_not_all_trivially_the_same_wording():
    """Guards against a degenerate corpus where every reaches_prompt payload reuses one
    literal string the pattern list happens to special-case -- widen coverage was an
    explicit goal of the 2026-08-23 fix, not just adding more copies of one payload."""
    live = [p for p in ALL_PAYLOADS if p.reaches_prompt]
    assert len(live) >= 5
    excerpts = {p.span_excerpt for p in live}
    assert len(excerpts) == len(live), "reaches_prompt payloads should carry distinct wording"


def test_structurally_inapplicable_payloads_are_declared_consistently():
    """s1/s4's XML-comment payloads are unreachable regardless of whether the scanner
    would catch them (comments never reach a job prompt at all) -- reaches_prompt=False
    must not be conflated with evades_detector, which is a separate, narrower claim
    about payloads that DO reach a prompt but slip past the heuristic."""
    inapplicable = [p for p in ALL_PAYLOADS if not p.reaches_prompt]
    assert len(inapplicable) == 3
    for p in inapplicable:
        assert p.landing_site.startswith("none"), p.payload_id
