"""Unit tests for the HMAC signing layer.

These vectors mirror the canonical Paradigm signing message described
in the API spec: ``<timestamp>\\n<METHOD>\\n<path-with-query>\\n<body>``.
"""

from __future__ import annotations

import base64
import hmac
from hashlib import sha256

import pytest

from mcp_paradigm.utils.signing import EnvKeySigner, build_message


def _expected(key_b64: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    """Independent reimplementation of the signing recipe for the assertion."""
    key = base64.b64decode(key_b64)
    msg = b"\n".join(
        [
            timestamp.encode("ascii"),
            method.upper().encode("ascii"),
            path.encode("utf-8"),
            body,
        ]
    )
    return base64.b64encode(hmac.new(key, msg, sha256).digest()).decode("ascii")


def test_build_message_layout() -> None:
    msg = build_message("1700000000000", "GET", "/v2/drfq/echo/", b"")
    assert msg == b"1700000000000\nGET\n/v2/drfq/echo/\n"


def test_env_key_signer_get() -> None:
    key_b64 = base64.b64encode(b"\x00" * 32).decode("ascii")
    signer = EnvKeySigner(signing_key_b64=key_b64)
    headers = signer.sign("GET", "/v2/drfq/echo/", b"")
    ts, sig = headers["Paradigm-API-Timestamp"], headers["Paradigm-API-Signature"]
    assert ts.isdigit() and len(ts) >= 13
    assert sig == _expected(key_b64, ts, "GET", "/v2/drfq/echo/", b"")


def test_env_key_signer_post_with_body() -> None:
    key_b64 = base64.b64encode(b"secret-key-bytes" * 2).decode("ascii")
    signer = EnvKeySigner(signing_key_b64=key_b64)
    body = b'{"hello":"world"}'
    headers = signer.sign("POST", "/v2/drfq/echo/", body)
    ts, sig = headers["Paradigm-API-Timestamp"], headers["Paradigm-API-Signature"]
    assert sig == _expected(key_b64, ts, "POST", "/v2/drfq/echo/", body)


def test_env_key_signer_path_with_query() -> None:
    key_b64 = base64.b64encode(b"abcdefgh" * 4).decode("ascii")
    signer = EnvKeySigner(signing_key_b64=key_b64)
    path = "/v2/drfq/instruments/?venue=DBT&base_currency=BTC"
    headers = signer.sign("GET", path, b"")
    ts, sig = headers["Paradigm-API-Timestamp"], headers["Paradigm-API-Signature"]
    assert sig == _expected(key_b64, ts, "GET", path, b"")


def test_env_key_signer_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARADIGM_SIGNING_KEY", raising=False)
    from mcp_paradigm.utils import config as cfg

    monkeypatch.setattr(cfg.config, "PARADIGM_SIGNING_KEY", None)
    with pytest.raises(ValueError):
        EnvKeySigner()
