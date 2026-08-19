# Security Policy

Assertion Desk is a solo-maintained security-triage lab, not a production system (see
`docs/LIMITATIONS.md`). It still handles SAML responses, certificates, and other sensitive
artifacts, so real vulnerability reports are welcome and taken seriously.

## Supported versions

There are no released versions or maintained branches. `main` is the only supported target;
fixes land there directly, not backported anywhere.

## Reporting a vulnerability

Preferred: use GitHub's [private vulnerability reporting](https://github.com/RasheedFarhat/assertion-desk/security/advisories/new)
for this repository. It opens a private draft advisory visible only to the maintainer until a
fix is ready.

If that is not available to you, email **rasheedfrht@gmail.com** with:

- A description of the issue and its impact.
- Steps to reproduce, or a minimal case under `corpus/cases/` that demonstrates it.
- Whether you consider it safe to disclose publicly once fixed.

Please do not open a public GitHub issue for a suspected vulnerability before it has been
triaged.

## What to expect

This is a solo project maintained outside of paid work, so response times are best-effort, not
SLA-backed. Expect an acknowledgment within a few days. Confirmed issues will be fixed on
`main` and credited in the fix's commit message unless you ask not to be named.

## Scope

In scope: anything in this repository, including the demo API (`desk/api.py`), the custody
detector (`desk/custody/`), the model fallback cascade (`desk/reason/`), and the n8n workflow
definitions (`n8n/`).

Out of scope: the third-party services this project integrates with (Gemini, Ollama, Keycloak,
n8n itself) unless the issue is in how this repository configures or calls them. Report those
upstream instead.
