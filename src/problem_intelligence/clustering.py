"""Deterministic fingerprinting and a conservative exact-match clustering baseline."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from .domain import ObservationRecord
from .repository import Repository

_NON_WORD = re.compile(r"[^\w]+", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_fingerprint_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _WHITESPACE.sub(" ", _NON_WORD.sub(" ", normalized)).strip()
    return normalized or None


def observation_fingerprint(observation: ObservationRecord) -> str:
    """Hash stable problem identity fields; evidence locality is intentionally excluded."""

    payload = {
        "actor": normalize_fingerprint_text(observation.actor),
        "context": normalize_fingerprint_text(observation.context),
        "job_to_be_done": normalize_fingerprint_text(observation.job_to_be_done),
        "problem": normalize_fingerprint_text(observation.problem),
        "root_cause": normalize_fingerprint_text(observation.root_cause),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ClusteringResult:
    algorithm_version: str
    observation_count: int
    cluster_count: int
    cluster_ids: tuple[int, ...]


def cluster_exact(
    repository: Repository, *, version: str = "exact-fingerprint-v1"
) -> ClusteringResult:
    observations = repository.clusterable_observations()
    assignments: dict[str, list[int]] = defaultdict(list)
    for observation in observations:
        assignments[observation_fingerprint(observation)].append(observation.id)
    cluster_ids = repository.store_cluster_assignments(
        algorithm_version=version,
        assignments=dict(assignments),
    )
    return ClusteringResult(version, len(observations), len(assignments), cluster_ids)
