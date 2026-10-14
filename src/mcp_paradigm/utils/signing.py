"""Pluggable signing layer for Paradigm HMAC auth.

The signing key never has to live in the agent process. Implementations
of ``Signer`` may compute HMAC locally (``EnvKeySigner``) or delegate to
a signing proxy (``ProxySigner``), Vault Transit, or AWS KMS. See ``DESIGN.md``.

Paradigm's signing message is the literal string::

    <timestamp_ms>\\n<METHOD>\\n<path-with-query>\\n<body>

signed with HMAC-SHA256 over the base64-decoded signing key, then
base64-encoded.
"""

from __future__ import annotations

import base64
import hmac
import logging
import time
from hashlib import sha256
from typing import Protocol, cast

from mcp_paradigm.utils.config import config

logger = logging.getLogger(__name__)

TIMESTAMP_HEADER = "Paradigm-API-Timestamp"
SIGNATURE_HEADER = "Paradigm-API-Signature"


class Signer(Protocol):
    """Sign a Paradigm REST request.

    Returns the headers to send: at least ``Paradigm-API-Timestamp`` and
    ``Paradigm-API-Signature``. The timestamp must be within 30s of
    Paradigm server time.
    """

    def sign(self, method: str, path: str, body_bytes: bytes) -> dict[str, str]: ...


def build_message(timestamp_ms: str, method: str, path: str, body_bytes: bytes) -> bytes:
    """Construct the canonical message Paradigm signs over."""
    return b"\n".join(
        [
            timestamp_ms.encode("ascii"),
            method.upper().encode("ascii"),
            path.encode("utf-8"),
            body_bytes,
        ]
    )


class EnvKeySigner:
    """Reads the signing key from env, computes HMAC in-process. Dev only."""

    def __init__(self, signing_key_b64: str | None = None) -> None:
        key = signing_key_b64 or config.PARADIGM_SIGNING_KEY
        if not key:
            raise ValueError("PARADIGM_SIGNING_KEY is not set; cannot use EnvKeySigner.")
        self._key = base64.b64decode(key)

    def sign(self, method: str, path: str, body_bytes: bytes) -> dict[str, str]:
        ts = _now_ms()
        msg = build_message(ts, method, path, body_bytes)
        digest = hmac.new(self._key, msg, sha256).digest()
        return {
            TIMESTAMP_HEADER: ts,
            SIGNATURE_HEADER: base64.b64encode(digest).decode("ascii"),
        }


class ProxySigner:
    """Leaves the HMAC to a signing proxy that holds the key.

    Sends the base64 signing message in ``header`` and ``placeholder`` as
    the signature, for the proxy to replace with the real one.
    """

    def __init__(self, header: str, placeholder: str) -> None:
        self._header = header
        self._placeholder = placeholder

    def sign(self, method: str, path: str, body_bytes: bytes) -> dict[str, str]:
        ts = _now_ms()
        msg = build_message(ts, method, path, body_bytes)
        return {
            TIMESTAMP_HEADER: ts,
            SIGNATURE_HEADER: self._placeholder,
            self._header: base64.b64encode(msg).decode("ascii"),
        }


def _now_ms() -> str:
    return str(int(time.time() * 1000))


def get_signer() -> Signer:
    """Resolve the Signer that ``PARADIGM_SIGNING_DRIVER`` names.

    ``env_key`` and ``proxy`` ship.
    """
    error = config.signer_config_error()
    if error:
        raise ValueError(error)
    driver = config.SIGNING_DRIVER.lower()
    if driver == "proxy":
        if config.PARADIGM_SIGNING_KEY:
            logger.warning(
                "PARADIGM_SIGNING_KEY is set but PARADIGM_SIGNING_DRIVER=proxy; the key is not used."
            )
        return ProxySigner(
            cast(str, config.PARADIGM_SIGNER_HEADER), cast(str, config.PARADIGM_SIGNER_SIGNATURE)
        )
    if driver == "env_key":
        return EnvKeySigner()
    raise NotImplementedError(
        f"Signing driver {driver!r} is not implemented; only 'env_key' and 'proxy' ship."
    )
