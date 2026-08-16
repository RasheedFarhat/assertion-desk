"""Drive a real browser through a FAILED login (wrong password) and capture the real HAR.

This is the negative_control fault's evidence: a real Keycloak login form rejecting a
real bad credential, so the HAR on disk shows an authentication failure page and, per the
assertion below, zero POSTs of a SAMLResponse to the SP's ACS endpoint anywhere in it.
Correct system behavior on this case is recognizing there is nothing to verify -- no
Response, no Assertion, no checks to run -- not synthesizing a result. This script only
proves the artifact is real; harness/faults/negative_control.py names what the system
must do with it.
"""

from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

CAPTURE_DIR = os.path.join(os.path.dirname(__file__), "fault_negative_control")
os.makedirs(CAPTURE_DIR, exist_ok=True)
HAR_PATH = os.path.join(CAPTURE_DIR, "login.har")
RESULT_PATH = os.path.join(CAPTURE_DIR, "capture_result.json")

SP_LOGIN_URL = "http://127.0.0.1:9091/saml/login"
USERNAME = "alice"
WRONG_PASSWORD = "definitely_not_the_password"


def run() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(record_har_path=HAR_PATH, record_har_content="embed")
        page = context.new_page()

        page.goto(SP_LOGIN_URL, wait_until="networkidle")
        page.wait_for_selector("#username", timeout=10000)
        page.fill("#username", USERNAME)
        page.fill("#password", WRONG_PASSWORD)
        page.click("#kc-login")

        page.wait_for_load_state("networkidle", timeout=10000)
        body_text = page.inner_text("body")
        final_url = page.url

        context.close()  # flushes the HAR to disk
        browser.close()

        with open(HAR_PATH) as f:
            har = json.load(f)
        entries = har["log"]["entries"]
        acs_posts = [
            e
            for e in entries
            if e["request"]["method"] == "POST" and "/saml/acs" in e["request"]["url"]
        ]

        result = {
            "final_url": final_url,
            "body_excerpt": body_text[:300],
            "num_har_entries": len(entries),
            "acs_posts_observed": len(acs_posts),
            "invalid_credentials_shown": "Invalid username or password" in body_text,
        }
        with open(RESULT_PATH, "w") as f:
            json.dump(result, f, indent=2)

        print(json.dumps(result, indent=2))
        assert len(acs_posts) == 0, "expected zero SAMLResponse POSTs to /saml/acs on a failed login"


if __name__ == "__main__":
    run()
