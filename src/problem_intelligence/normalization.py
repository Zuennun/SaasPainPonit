"""Identity normalization used by ingestion and deduplication."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

_WHITESPACE = re.compile(r"\s+")


def normalize_identifier(value: str) -> str:
    """Normalize a provider identifier without destroying meaningful punctuation."""

    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = _WHITESPACE.sub(" ", normalized)
    if not normalized:
        raise ValueError("identifier must not be empty")
    return normalized


def normalize_url(value: str | None) -> str | None:
    """Normalize the stable parts of a URL while retaining path case and query.

    Embedded userinfo (``user:password@host``) is dropped rather than preserved.
    Normalized URLs are stored as public source/competitor identity and surfaced
    verbatim in reports and exports; there is no legitimate case in this system
    for persisting or displaying credentials that happened to be pasted into a
    source URL, and retaining them would silently leak them into evidence output.
    """

    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("source URL must be an absolute HTTP(S) URL")
    host = parts.hostname.casefold() if parts.hostname else ""
    port = f":{parts.port}" if parts.port else ""
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), f"{host}{port}", path, parts.query, ""))
