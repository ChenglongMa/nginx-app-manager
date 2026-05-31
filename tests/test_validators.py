from __future__ import annotations

import pytest

from nam.utils.validators import (
    ValidationError,
    normalize_domain,
    safe_domain_filename,
    validate_port_number,
    validate_upstream_host,
)


def test_normalize_domain_accepts_subdomain() -> None:
    assert normalize_domain("app1.example.com.") == "app1.example.com"


@pytest.mark.parametrize(
    "domain",
    ["localhost", "../bad.example.com", "-bad.example.com", "bad..com"],
)
def test_normalize_domain_rejects_invalid_values(domain: str) -> None:
    with pytest.raises(ValidationError):
        normalize_domain(domain)


def test_safe_domain_filename() -> None:
    assert safe_domain_filename("demo.example.com") == "demo.example.com.conf"


@pytest.mark.parametrize("port", [1, 8080, 65535])
def test_validate_port_number_accepts_valid_ports(port: int) -> None:
    assert validate_port_number(port) == port


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_validate_port_number_rejects_invalid_ports(port: int) -> None:
    with pytest.raises(ValidationError):
        validate_port_number(port)


def test_validate_upstream_host_rejects_urls_and_paths() -> None:
    with pytest.raises(ValidationError):
        validate_upstream_host("http://127.0.0.1")
    with pytest.raises(ValidationError):
        validate_upstream_host("../socket")
