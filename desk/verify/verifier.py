"""Orchestrates all ~20 checks (desk/verify/checks/) against one SAMLResponse.

Two failure modes are handled deliberately rather than left to bubble up as crashes:
  1. The response doesn't parse at all (desk.verify.parsed.MalformedSamlResponse) -- no
     check can run, so the run reports that plainly rather than a report full of
     NOT_VERIFIED rows that all say the same thing for the same underlying reason.
  2. A single check raises unexpectedly -- a bug in one check must never take the whole
     run down, and it must never silently disappear either. It's captured as its own
     CheckResult (NOT_VERIFIED, reason names the exception) so a broken check shows up as
     a finding in its own row, not as a stack trace in a log nobody reads during a demo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.checks import ALL_CHECKS
from desk.verify.context import VerificationContext
from desk.verify.parsed import MalformedSamlResponse, parse_saml_response


@dataclass
class VerificationRun:
    parse_error: str | None
    results: list[CheckResult] = field(default_factory=list)

    def by_id(self, check_id: str) -> CheckResult | None:
        return next((r for r in self.results if r.check_id == check_id), None)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {a.value: 0 for a in Assurance}
        for r in self.results:
            out[r.assurance.value] += 1
        return out

    def has_any_failed(self) -> bool:
        return any(r.assurance == Assurance.FAILED for r in self.results)


def run_all_checks(raw_bytes: bytes, ctx: VerificationContext) -> VerificationRun:
    try:
        parsed = parse_saml_response(raw_bytes)
    except MalformedSamlResponse as exc:
        return VerificationRun(parse_error=str(exc))

    run = VerificationRun(parse_error=None)
    for check_fn in ALL_CHECKS:
        try:
            run.results.append(check_fn(parsed, ctx))
        except Exception as exc:  # noqa: BLE001 -- a broken check must become a finding, not a crash
            check_id = getattr(check_fn, "__name__", "unknown_check")
            run.results.append(
                CheckResult(
                    check_id=check_id,
                    assurance=Assurance.NOT_VERIFIED,
                    observed=None,
                    expected=None,
                    reason=f"check raised an unexpected exception: {exc!r}",
                )
            )
    return run


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "harness/capture/captured/saml_response.xml"
    cert_path = sys.argv[2] if len(sys.argv) > 2 else "harness/capture/idp-cert.txt"
    with open(path, "rb") as f:
        data = f.read()
    try:
        with open(cert_path) as f:
            trusted_cert = f.read()
    except FileNotFoundError:
        trusted_cert = None

    # No evaluation_time pin here deliberately: this is a live debug CLI, not a test, so
    # it should judge against real wall-clock time (ctx.now()'s default) rather than a
    # frozen instant that would drift stale as soon as a fixture ages past it.
    ctx = VerificationContext(
        sp_entity_id="http://127.0.0.1:9091/saml/metadata",
        acs_url="http://127.0.0.1:9091/saml/acs",
        idp_entity_id="http://127.0.0.1:8080/realms/assertion-desk",
        trusted_cert_pem=trusted_cert,
    )
    run = run_all_checks(data, ctx)
    if run.parse_error:
        print("PARSE ERROR:", run.parse_error)
        sys.exit(1)
    for r in run.results:
        print(f"{r.check_id:16s} {r.assurance.value:16s} {r.reason}")
    print()
    print("counts:", run.counts())
