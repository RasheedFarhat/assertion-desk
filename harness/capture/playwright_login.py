"""Drive a real browser through the SP -> Keycloak -> SP SAML login, capturing a real HAR.

This is Phase 0's other de-risked artifact: the HAR is not authored, it is what
Playwright's recordHar actually observed on the wire during a real login against the
Keycloak instance stood up by keycloak_admin.py.
"""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

CAPTURE_DIR = os.path.join(os.path.dirname(__file__), "captured")
os.makedirs(CAPTURE_DIR, exist_ok=True)
HAR_PATH = os.path.join(CAPTURE_DIR, "login.har")

SP_LOGIN_URL = "http://127.0.0.1:9091/saml/login"
USERNAME = "alice"
PASSWORD = "alice_dev_only"


def run() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(record_har_path=HAR_PATH, record_har_content="embed")
        page = context.new_page()

        page.goto(SP_LOGIN_URL, wait_until="networkidle")

        # Keycloak's default login form: username/password fields, standard IDs.
        page.wait_for_selector("#username", timeout=10000)
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("#kc-login")

        page.wait_for_load_state("networkidle", timeout=10000)
        body_text = page.inner_text("body")

        context.close()  # flushes the HAR to disk
        browser.close()

        print("final page body:", body_text[:300])
        print("HAR written to:", HAR_PATH)


if __name__ == "__main__":
    run()
