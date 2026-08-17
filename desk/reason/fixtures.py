"""Deterministic replay of recorded model responses. `make eval-replay` (plan section
23/36 verification step 5) has to reproduce published numbers with no API key and no
network -- this is the mechanism that makes that true. A fixture is keyed on
sha256(prompt) + model_id + schema_version, so a prompt-template change or a schema
bump invalidates old fixtures instead of silently replaying a stale-shaped response
against new code.

Fixtures are plain JSON files under `fixtures/`, one per key, and are meant to be
committed -- they are this project's frozen, checksummable record of what a real model
actually said, in the same spirit as corpus/MANIFEST.json for the fault corpus.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from desk.reason.client import ModelResponse
from desk.reason.schemas import SCHEMA_VERSION

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


def fixture_key(prompt: str, model_id: str, schema_version: str = SCHEMA_VERSION) -> str:
    digest = hashlib.sha256()
    digest.update(prompt.encode("utf-8"))
    digest.update(b"\0")
    digest.update(model_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(schema_version.encode("utf-8"))
    return digest.hexdigest()


def deterministic_marker_key(prompt: str, schema_version: str = SCHEMA_VERSION) -> str:
    """Key for the "this exact prompt legitimately exhausts every live tier and
    terminates in the deterministic template" marker -- deliberately not keyed on
    model_id, because the marker records a fact about the prompt (every configured
    client was tried and none answered), not about any one model's response."""
    digest = hashlib.sha256()
    digest.update(prompt.encode("utf-8"))
    digest.update(b"\0")
    digest.update(schema_version.encode("utf-8"))
    return digest.hexdigest()


class FixtureCache:
    def __init__(self, directory: Path | str = DEFAULT_FIXTURE_DIR) -> None:
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def _deterministic_path(self, key: str) -> Path:
        # Separate subdirectory, not the flat fixture namespace: a deterministic
        # marker is not a recorded model response (it has no provider, tokens, or
        # transcript to audit) and must never be mistaken for one by anything that
        # globs fixtures/*.json expecting ModelResponse-shaped records (e.g. the
        # secret-leakage scanner in eval/metrics.py, which scans stored prompts).
        return self.directory / "_deterministic" / f"{key}.json"

    def is_marked_deterministic(self, prompt: str, schema_version: str = SCHEMA_VERSION) -> bool:
        """True if a prior live run already discovered that every configured client
        exhausts on this exact prompt, so replay can terminate in the deterministic
        template instead of raising ReplayMiss. This is what lets `make eval-replay`
        reproduce a live run's numbers even for the cases that themselves fell back to
        deterministic -- without it, replay-only had no way to distinguish "this
        prompt was never run live" (a genuine gap, should raise) from "this prompt was
        run live and correctly fell through to deterministic" (should not raise)."""
        return self._deterministic_path(deterministic_marker_key(prompt, schema_version)).exists()

    def mark_deterministic(self, prompt: str, schema_version: str = SCHEMA_VERSION) -> None:
        """Records that a live run tried every configured client for this prompt and
        none answered, so it terminated in the deterministic template. Stores the
        prompt alongside the marker (as fixtures do for model responses) so the
        marker stays auditable -- a reviewer can see exactly which prompt this
        applies to, not just an opaque hash."""
        key = deterministic_marker_key(prompt, schema_version)
        path = self._deterministic_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            "schema_version": schema_version,
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "recorded_at": time.time(),
        }
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    def get(
        self, prompt: str, model_id: str, schema_version: str = SCHEMA_VERSION
    ) -> ModelResponse | None:
        """Returns the cached ModelResponse, or None on a miss. A miss is not an
        error -- callers (desk/reason/fallback.py) decide what a miss means: fall
        through to a live provider, or raise if running in replay-only mode."""
        path = self._path(fixture_key(prompt, model_id, schema_version))
        if not path.exists():
            return None
        record = json.loads(path.read_text())
        return ModelResponse(
            text=record["text"],
            provider=record["provider"],
            model_id=record["model_id"],
            input_tokens=record.get("input_tokens"),
            output_tokens=record.get("output_tokens"),
            latency_ms=record.get("latency_ms", 0.0),
        )

    def put(
        self,
        prompt: str,
        model_id: str,
        response: ModelResponse,
        schema_version: str = SCHEMA_VERSION,
    ) -> str:
        """Persists a real response and returns the key it was stored under. The full
        prompt is stored alongside the response (not just its hash) so a committed
        fixture doubles as an auditable transcript -- matching the case card's "show
        exactly what the model was sent" requirement (plan section 22) for the cases
        used to produce published numbers.

        Write-once. If a fixture already exists for this key, it is left untouched and
        this call is a no-op -- confirmed necessary 2026-08-17, when a second live call
        to a prompt that already had a recorded fixture (itself a symptom of Ollama's
        per-request seed non-determinism, see the client's seed comment) silently
        overwrote a fixture that had backed a previously published number with a
        different, unreviewed answer. A fixture is meant to be this project's frozen,
        checksummable record of what a real model actually said (see module docstring);
        silently replacing that record on a later, unrelated live call contradicts the
        whole reason fixtures exist. The first real response recorded for a prompt is
        the one that stays authoritative for replay."""
        key = fixture_key(prompt, model_id, schema_version)
        existing = self._path(key)
        if existing.exists():
            return key
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            "schema_version": schema_version,
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "model_id": response.model_id,
            "provider": response.provider,
            "text": response.text,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "latency_ms": response.latency_ms,
            "recorded_at": time.time(),
        }
        self._path(key).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        return key
