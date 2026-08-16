"""The audit-trail aggregate built from a CustodyResult.

Where CustodyFinding (findings.py) is one row per redacted/recorded value and
CustodyResult (scan.py) is the raw output of a single scan call, CustodyRecord is the
persisted summary attached to one Artifact -- plan section 19's CustodyRecord table is
one row per CustodyFinding, and this module's CustodyRecord is a canonical, hashable
rollup of all of them for a single artifact. It matches the "custody record sha256:
4f2b..." line in the plan's section 13 demo script, and it's built to chain the same
way Control Plane's evidence ledger does (TraceEvent.prev_hash from GENESIS): a later
TraceEvent can use this record's sha256 directly as the payload hash for its custody
stage, without recomputing anything.

The hash is computed over a canonical JSON encoding of the finding list -- sorted rows,
sorted keys, no separators -- so the same set of findings always hashes identically
regardless of the order they were appended in during the scan. Two runs that find the
identical set of secrets always produce the identical hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from desk.custody.findings import CustodyFinding
from desk.custody.scan import CustodyResult


def _canonical_finding_dict(finding: CustodyFinding) -> dict:
    return {
        "finding_class": finding.finding_class.value,
        "location": finding.location,
        "placeholder_token": finding.placeholder_token,
        "liveness": finding.liveness.value,
        "action": finding.action.value,
        "detector": finding.detector,
        "detector_version": finding.detector_version,
    }


def _canonical_json(findings: list[CustodyFinding]) -> bytes:
    rows = [_canonical_finding_dict(f) for f in findings]
    # Sort rows themselves, not just keys within each row -- two scans that found the
    # same findings but appended them in a different order (e.g. the cross-artifact
    # sweep's iteration order depends on dict insertion order) must still hash equal.
    rows.sort(key=lambda r: json.dumps(r, sort_keys=True))
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class CustodyRecord:
    artifact_id: str
    findings: list[CustodyFinding]
    sha256: str
    counts_by_class: dict[str, int]
    any_live_credential: bool

    def to_summary_dict(self) -> dict:
        """What the case card (plan section 22's custody panel) actually renders --
        counts and a hash, never a raw value or even a raw finding list."""
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "counts_by_class": dict(self.counts_by_class),
            "any_live_credential": self.any_live_credential,
            "total_findings": len(self.findings),
        }


def build_custody_record(artifact_id: str, result: CustodyResult) -> CustodyRecord:
    """The one entry point desk/case calls after run_custody() returns. Deliberately
    takes the already-computed CustodyResult rather than re-scanning -- this module has
    no detector logic of its own, only aggregation and hashing."""
    digest = hashlib.sha256(_canonical_json(result.findings)).hexdigest()
    counts: dict[str, int] = {}
    for f in result.findings:
        counts[f.finding_class.value] = counts.get(f.finding_class.value, 0) + 1
    return CustodyRecord(
        artifact_id=artifact_id,
        findings=list(result.findings),
        sha256=digest,
        counts_by_class=counts,
        any_live_credential=result.any_live_credential,
    )
