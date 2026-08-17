"""End-to-end tests for desk/api.py against Flask's test client and real corpus cases.
Reuses the exact four corpus cases tests/case/test_orchestrate.py already established as
covering REASONED, AWAITING_EVIDENCE, HUMAN_REVIEW, and ESCALATED, so this module adds
HTTP-surface coverage without re-deriving which case lands where."""

from __future__ import annotations

import json

import pytest

from desk.api import create_app
from desk.case.state import CaseState, new_case
from desk.case.store import CaseStore, connect


@pytest.fixture()
def app():
    return create_app(store=CaseStore(connect(":memory:")))


@pytest.fixture()
def client(app):
    return app.test_client()


def _post_case(client, corpus_case: str, **extra):
    return client.post("/cases", json={"corpus_case": corpus_case, **extra})


# --------------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------------- #


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


# --------------------------------------------------------------------------------- #
# POST /cases -- validation
# --------------------------------------------------------------------------------- #


def test_create_case_without_corpus_case_is_400(client):
    resp = client.post("/cases", json={})
    assert resp.status_code == 400


def test_create_case_unknown_corpus_case_is_404_with_known_list(client):
    resp = client.post("/cases", json={"corpus_case": "does-not-exist"})
    assert resp.status_code == 404
    body = resp.get_json()
    assert "known_corpus_cases" in body
    assert "cert_expired" in body["known_corpus_cases"]


# --------------------------------------------------------------------------------- #
# POST /cases -- real corpus cases, matching tests/case/test_orchestrate.py exactly
# --------------------------------------------------------------------------------- #


def test_cert_expired_reaches_reasoned(client):
    resp = _post_case(client, "cert_expired")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["state"] == CaseState.REASONED.value
    assert body["disposition"] == "review_required"


def test_withheld_clock_reaches_awaiting_evidence(client):
    resp = _post_case(client, "withheld_clock")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["state"] == CaseState.AWAITING_EVIDENCE.value
    assert body["disposition"] == "awaiting_evidence"


def test_negative_control_reaches_human_review(client):
    resp = _post_case(client, "negative_control")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["state"] == CaseState.HUMAN_REVIEW.value
    assert body["disposition"] == "review_required"


def test_truncated_response_reaches_escalated(client):
    resp = _post_case(client, "truncated_response")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["state"] == CaseState.ESCALATED.value
    assert body["disposition"] == "escalate"


# --------------------------------------------------------------------------------- #
# GET /cases/<id> -- detail, trace, chain validity
# --------------------------------------------------------------------------------- #


def test_get_case_returns_trace_chain_and_detail(client):
    created = _post_case(client, "cert_expired").get_json()
    resp = client.get(f"/cases/{created['id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == created["id"]
    assert body["chain_valid"] is True
    assert len(body["trace"]) >= 2  # at least intake + verify
    assert body["detail"] is not None
    assert body["detail"]["corpus_case"] == "cert_expired"
    assert body["detail"]["final_root_cause"] is not None
    assert "checks" in body["detail"]
    assert "A" in body["detail"]["jobs"] or "C" in body["detail"]["jobs"]


def test_get_case_missing_is_404(client):
    resp = client.get("/cases/no-such-case")
    assert resp.status_code == 404


def test_detail_cache_miss_degrades_honestly(app, client):
    # A case inserted directly into the store, bypassing POST /cases, has no
    # detail_cache entry -- GET /cases/<id> must degrade to durable fields only,
    # not crash and not fabricate detail.
    case = new_case(id="bare-case", correlation_id="corr-bare", state=CaseState.VERIFYING)
    app.store.insert_case(case)

    resp = client.get("/cases/bare-case")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["detail"] is None
    assert "detail_note" in body


# --------------------------------------------------------------------------------- #
# GET /cases/<id>/card -- HTML case card
# --------------------------------------------------------------------------------- #


def test_get_case_card_renders_html(client):
    created = _post_case(client, "cert_expired").get_json()
    resp = client.get(f"/cases/{created['id']}/card")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    html_text = resp.get_data(as_text=True)
    assert created["id"] in html_text
    assert "<html>" in html_text


def test_get_case_card_missing_is_404_html(client):
    resp = client.get("/cases/no-such-case/card")
    assert resp.status_code == 404
    assert resp.mimetype == "text/html"


# --------------------------------------------------------------------------------- #
# GET /cases -- listing and state filter
# --------------------------------------------------------------------------------- #


def test_list_cases_filters_by_state(client):
    _post_case(client, "cert_expired")
    _post_case(client, "withheld_clock")

    resp = client.get("/cases", query_string={"state": "reasoned"})
    assert resp.status_code == 200
    cases = resp.get_json()["cases"]
    assert len(cases) == 1
    assert cases[0]["state"] == "reasoned"


def test_list_cases_unknown_state_is_400(client):
    resp = client.get("/cases", query_string={"state": "not-a-real-state"})
    assert resp.status_code == 400


def test_list_cases_unfiltered_returns_everything(client):
    _post_case(client, "cert_expired")
    _post_case(client, "withheld_clock")

    resp = client.get("/cases")
    assert resp.status_code == 200
    assert len(resp.get_json()["cases"]) == 2


# --------------------------------------------------------------------------------- #
# Human review lifecycle: post-for-review -> decision -> publish
# --------------------------------------------------------------------------------- #


def test_full_lifecycle_review_approve_publish(client):
    created = _post_case(client, "negative_control").get_json()
    case_id = created["id"]
    assert created["state"] == CaseState.HUMAN_REVIEW.value

    approve = client.post(
        f"/cases/{case_id}/decision",
        json={"approver": "analyst@example.com", "decision": "approved", "channel": "gmail"},
    )
    assert approve.status_code == 200
    approve_body = approve.get_json()
    assert approve_body["case"]["state"] == CaseState.APPROVED.value
    assert approve_body["approval"]["decision"] == "approved"

    publish = client.post(f"/cases/{case_id}/publish")
    assert publish.status_code == 200
    assert publish.get_json()["state"] == CaseState.PUBLISHED.value

    final = client.get(f"/cases/{case_id}").get_json()
    assert len(final["approvals"]) == 1
    assert final["chain_valid"] is True


def test_reasoned_case_must_be_posted_for_review_before_decision(client):
    created = _post_case(client, "cert_expired").get_json()
    case_id = created["id"]
    assert created["state"] == CaseState.REASONED.value

    post_review = client.post(f"/cases/{case_id}/post-for-review")
    assert post_review.status_code == 200
    assert post_review.get_json()["state"] == CaseState.HUMAN_REVIEW.value

    decision = client.post(
        f"/cases/{case_id}/decision",
        json={"approver": "analyst@example.com", "decision": "approved", "channel": "gmail"},
    )
    assert decision.status_code == 200
    assert decision.get_json()["case"]["state"] == CaseState.APPROVED.value


def test_post_for_review_illegal_from_awaiting_evidence_is_409(client):
    created = _post_case(client, "withheld_clock").get_json()
    resp = client.post(f"/cases/{created['id']}/post-for-review")
    assert resp.status_code == 409


def test_decision_escalated_requires_override_reason(client):
    created = _post_case(client, "negative_control").get_json()
    resp = client.post(
        f"/cases/{created['id']}/decision",
        json={"approver": "analyst@example.com", "decision": "escalated", "channel": "gmail"},
    )
    assert resp.status_code == 400


def test_decision_escalated_with_reason_succeeds(client):
    created = _post_case(client, "negative_control").get_json()
    resp = client.post(
        f"/cases/{created['id']}/decision",
        json={
            "approver": "analyst@example.com",
            "decision": "escalated",
            "channel": "gmail",
            "override_reason": "needs a second opinion",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["case"]["state"] == CaseState.ESCALATED.value


def test_decision_missing_fields_is_400(client):
    created = _post_case(client, "negative_control").get_json()
    resp = client.post(f"/cases/{created['id']}/decision", json={"approver": "a"})
    assert resp.status_code == 400


def test_decision_on_missing_case_is_404(client):
    resp = client.post(
        "/cases/no-such-case/decision",
        json={"approver": "a", "decision": "approved", "channel": "gmail"},
    )
    assert resp.status_code == 404


def test_publish_before_approved_is_409(client):
    created = _post_case(client, "cert_expired").get_json()
    resp = client.post(f"/cases/{created['id']}/publish")
    assert resp.status_code == 409
