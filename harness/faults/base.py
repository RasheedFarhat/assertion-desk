"""FaultSpec: the one shape every fault injector in this package conforms to.

Three genuinely different mechanisms produce the ~19 faults in this catalogue, and
mixing them into one dishonest "the harness broke Keycloak 19 ways" story would misstate
what actually happened. This module makes the mechanism a required, visible field rather
than an implementation detail buried in a docstring:

  LIVE_CAPTURE       -- a real Keycloak/SP misconfiguration, captured via a fresh
                        Playwright login. The artifact bytes come from real identity
                        software making a real mistake. Only cert_rotation (Phase 0) and
                        negative_control (this phase) use this path -- see
                        docs/PHASE3_NOTES.md for why the rest don't need to.
  CONTEXT_MISMATCH   -- the SAMLResponse bytes are real and unmodified (the one good
                        capture from Phase 0). The fault is that the SP's *own*
                        configuration -- its expected entity ID, ACS URL, IdP issuer,
                        clock, or prior request ID -- has drifted from what the response
                        reflects. This is how most of these misconfigurations actually
                        happen in production: nobody hand-edits a SAMLResponse, an admin
                        changes one side's config. Modeled here as a VerificationContext
                        override, not a byte mutation.
  ARTIFACT_MUTATION  -- Keycloak's default SAML client cannot organically produce this
                        shape (a broken signature, a stripped NameID, a truncated
                        response body). The real captured bytes are deterministically
                        mutated, and the mutation function is committed and inspectable
                        -- never a hand-edited one-off file with no record of what changed.
  DOCUMENTED_GAP     -- a fault class the catalogue considered and did not build an
                        executable case for, because doing so honestly would require
                        capability the verifier does not have yet (see sha1_downgrade.py).
                        Recorded so the gap is visible, not silently dropped from the count.

A fifth value, BASELINE, exists for exactly one case outside this file's own ~19-fault
count (harness/faults/conflicting.py, in the corpus's "conflicting" difficulty stratum,
never added to ALL_FAULTS): the real Phase 0 capture, completely untouched -- no
ctx_transform, no xml_transform, no har_transform. It earns its own category rather than
being mislabeled CONTEXT_MISMATCH because nothing has drifted and nothing was overridden;
the real assertion's own six duplicate Attribute Name values (SAML-ATTR-01) are why that
one case belongs in the corpus at all. Calling that CONTEXT_MISMATCH would claim a
transform happened when none did.

Every FaultSpec also carries target_check_ids: the check(s) in desk/verify/checks/ that
should fire on this fault. This is what Phase 3's "label sanity" test (every fault ID
maps to a detectable check) actually checks -- a FaultSpec with no target_check_ids must
be DOCUMENTED_GAP, or must name why not, never silently empty. Two narrower escape
hatches exist for the two honest ways an *executable* fault can still have no
target_check_ids:

  expects_parse_failure  -- the mutation is severe enough that desk/verify/parsed.py
                             raises MalformedSamlResponse before any check ever runs (the
                             malformed stratum: truncation, double-encoding). There is no
                             CheckResult to name because verification never starts --
                             this is an intake-stage rejection, not a check failure.
  no_check_coverage_reason -- the case is real and verification runs to completion, but
                             no check in the current catalogue reads the artifact this
                             fault touches (e.g. RelayState, the SAML binding type -- both
                             live in the HAR/transport layer, not the parsed SAMLResponse
                             desk/verify/checks/ operates on). Recorded explicitly as a
                             coverage gap rather than silently omitted from the corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, TypedDict

from desk.verify.context import VerificationContext


class FaultCategory(str, Enum):
    LIVE_CAPTURE = "live_capture"
    CONTEXT_MISMATCH = "context_mismatch"
    ARTIFACT_MUTATION = "artifact_mutation"
    DOCUMENTED_GAP = "documented_gap"
    BASELINE = "baseline"


class LiveArtifacts(TypedDict, total=False):
    """What harness/generate.py needs back from a LIVE_CAPTURE fault's live_loader.

    live_dir alone (a bare directory name) turned out not to be enough of an interface:
    cert_rotation's directory holds four files playing three different roles (a
    pre-rotation response that's there for comparison and never loaded, a post-rotation
    response that IS the case, and two candidate trusted certs where only the stale one
    belongs in this case's context), and negative_control's directory holds a real HAR
    but deliberately no SAMLResponse at all. A generic "copy every file in live_dir"
    rule would have to guess at that shape per fault. live_loader is each fault's own
    small, explicit answer to "which files, playing which roles" -- so generate.py's
    interface for LIVE_CAPTURE stays exactly one function call, same as every other
    category, while the fault module keeps full ownership of what its directory means.
    """

    raw_saml_response: bytes | None  # None only when no_saml_response_reason is set
    trusted_cert_pem: str | None  # overrides baseline.good_context()'s cert when set
    har_path: str | None  # absolute path to a real HAR to attach to the case, if any
    no_saml_response_reason: str | None  # set only when raw_saml_response is None


# Type aliases for the callable shapes a FaultSpec may carry.
CtxTransform = Callable[[VerificationContext], VerificationContext]
BytesTransform = Callable[[bytes], bytes]
HarTransform = Callable[[dict], dict]
LiveLoader = Callable[[], LiveArtifacts]


@dataclass(frozen=True)
class FaultSpec:
    fault_id: str
    category: FaultCategory
    description: str

    # Which desk/verify check(s) this fault should cause to fire, and what state they
    # should land in. Empty only for DOCUMENTED_GAP, and even then a reason is required.
    target_check_ids: list[str] = field(default_factory=list)
    expected_states: dict[str, str] = field(default_factory=dict)  # check_id -> Assurance.value

    # What the corpus label (EvalLabel, plan section 19) should say.
    expected_root_cause: str | None = None
    expected_disposition: str = "review_required"  # auto | review_required | escalate | awaiting_evidence
    difficulty: str = "normal"  # normal | ambiguous | conflicting | adversarial | malformed

    # Exactly one of these is set, depending on category. CONTEXT_MISMATCH sets
    # ctx_transform; ARTIFACT_MUTATION sets xml_transform and/or har_transform;
    # LIVE_CAPTURE sets live_dir (a harness/capture/ subdirectory holding real artifacts
    # already captured); DOCUMENTED_GAP sets none of them.
    ctx_transform: CtxTransform | None = None
    xml_transform: BytesTransform | None = None
    har_transform: HarTransform | None = None
    live_dir: str | None = None  # documentary: which harness/capture/ subdir this came from
    live_loader: LiveLoader | None = None  # required alongside live_dir -- see LiveArtifacts

    gap_reason: str | None = None  # required, and only meaningful, for DOCUMENTED_GAP

    # The two narrow, named escape hatches for an *executable* fault with no
    # target_check_ids -- see the module docstring. Exactly one may substitute for
    # target_check_ids; both being set on the same fault would conflate two different
    # kinds of gap, so that combination is also rejected below.
    expects_parse_failure: bool = False
    no_check_coverage_reason: str | None = None

    def __post_init__(self) -> None:
        if self.category == FaultCategory.DOCUMENTED_GAP:
            if not self.gap_reason:
                raise ValueError(f"{self.fault_id}: DOCUMENTED_GAP requires gap_reason")
            return
        if self.category == FaultCategory.LIVE_CAPTURE and (not self.live_dir or not self.live_loader):
            raise ValueError(f"{self.fault_id}: LIVE_CAPTURE requires both live_dir and live_loader")
        if self.expects_parse_failure and self.no_check_coverage_reason:
            raise ValueError(
                f"{self.fault_id}: set at most one of expects_parse_failure / "
                "no_check_coverage_reason -- they name two different kinds of gap"
            )
        if not self.target_check_ids and not self.expects_parse_failure and not self.no_check_coverage_reason:
            raise ValueError(
                f"{self.fault_id}: {self.category.value} faults must name at least one "
                "target_check_id, or set expects_parse_failure, or set "
                "no_check_coverage_reason -- an executable fault with no expected outcome "
                "of any of those three kinds is exactly the silent drift this dataclass "
                "exists to prevent"
            )
