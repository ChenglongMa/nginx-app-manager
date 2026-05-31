"""Input validators for domains, ports, and generated filenames."""

from __future__ import annotations

import re

DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
UPSTREAM_HOST_RE = re.compile(r"^[A-Za-z0-9_.:\-\[\]]+$")


class ValidationError(ValueError):
    """Raised when a user-supplied value is unsafe or invalid."""


def normalize_domain(domain: str) -> str:
    """Normalize and validate a fully qualified domain name."""
    candidate = domain.strip().lower().rstrip(".")
    if not candidate:
        raise ValidationError("Domain is required.")
    if any(token in candidate for token in ("/", "\\", "\x00", "..")):
        raise ValidationError("Domain contains unsafe path characters.")
    if len(candidate) > 253:
        raise ValidationError("Domain is longer than 253 characters.")

    labels = candidate.split(".")
    if len(labels) < 2:
        raise ValidationError("Domain must be a fully qualified domain name.")
    if any(not DOMAIN_LABEL_RE.match(label) for label in labels):
        raise ValidationError("Domain contains an invalid DNS label.")
    return candidate


def validate_port_number(port: int) -> int:
    """Validate a TCP port number."""
    if not isinstance(port, int):
        raise ValidationError("Port must be an integer.")
    if port < 1 or port > 65535:
        raise ValidationError("Port must be between 1 and 65535.")
    return port


def validate_upstream_host(host: str) -> str:
    """Validate a proxy upstream host without accepting URLs or paths."""
    candidate = host.strip()
    if not candidate:
        raise ValidationError("Upstream host is required.")
    if "://" in candidate or "/" in candidate or "\\" in candidate or "\x00" in candidate:
        raise ValidationError("Upstream host must be a host/IP, not a URL or path.")
    if not UPSTREAM_HOST_RE.match(candidate):
        raise ValidationError("Upstream host contains unsafe characters.")
    return candidate


def safe_domain_filename(domain: str) -> str:
    """Return a safe Nginx config filename for a managed domain."""
    normalized = normalize_domain(domain)
    return f"{normalized}.conf"
