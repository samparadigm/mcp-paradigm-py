"""Configuration for the MCP Paradigm server.

Loads from environment variables (and `.env` via python-dotenv). All
secrets are read at startup; everything else has sensible defaults.
"""

import os
from enum import StrEnum

from dotenv import load_dotenv

load_dotenv()


def _sanitize_env(value: str | None) -> str | None:
    """Return None for unsubstituted template variables like ${user_config.foo}."""
    if value and value.startswith("${") and value.endswith("}"):
        return None
    return value or None


class Environment(StrEnum):
    TESTNET = "testnet"
    PROD = "prod"


_PROD_REST = "https://api.prod.paradigm.trade"
_TEST_REST = "https://api.testnet.paradigm.trade"
_PROD_WS = "wss://ws.api.prod.paradigm.trade/v2/drfq/"
_TEST_WS = "wss://ws.api.testnet.paradigm.trade/v2/drfq/"
_PROD_FSPD = "https://api.fs.prod.paradigm.co"
_TEST_FSPD = "https://api.fs.testnet.paradigm.co"


class Config:
    """Runtime configuration for the MCP Paradigm server."""

    SERVER_NAME: str = os.getenv("SERVER_NAME", "Paradigm DRFQv2")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "3000"))

    ENVIRONMENT: str = os.getenv("PARADIGM_ENVIRONMENT", "prod")

    PARADIGM_BASE_URL: str | None = _sanitize_env(os.getenv("PARADIGM_BASE_URL"))
    PARADIGM_WS_URL: str | None = _sanitize_env(os.getenv("PARADIGM_WS_URL"))
    PARADIGM_FSPD_BASE_URL: str | None = _sanitize_env(os.getenv("PARADIGM_FSPD_BASE_URL"))

    PARADIGM_ACCESS_KEY: str | None = _sanitize_env(os.getenv("PARADIGM_ACCESS_KEY"))
    PARADIGM_SIGNING_KEY: str | None = _sanitize_env(os.getenv("PARADIGM_SIGNING_KEY"))
    PARADIGM_ACCOUNT: str | None = _sanitize_env(os.getenv("PARADIGM_ACCOUNT"))

    SIGNING_DRIVER: str = os.getenv("PARADIGM_SIGNING_DRIVER", "env_key")

    # Signing proxy: the proxy holds the key and replaces the placeholder signature.
    PARADIGM_SIGNER_HEADER: str | None = _sanitize_env(os.getenv("PARADIGM_SIGNER_HEADER"))
    PARADIGM_SIGNER_SIGNATURE: str | None = _sanitize_env(os.getenv("PARADIGM_SIGNER_SIGNATURE"))

    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("PARADIGM_TIMEOUT", "30"))

    WS_BUFFER_MAX_EVENTS: int = int(os.getenv("PARADIGM_WS_BUFFER", "1000"))
    WS_BUFFER_TTL_SECONDS: int = int(os.getenv("PARADIGM_WS_TTL", "600"))

    @classmethod
    def base_url(cls) -> str:
        if cls.PARADIGM_BASE_URL:
            return cls.PARADIGM_BASE_URL.rstrip("/")
        return _TEST_REST if cls.ENVIRONMENT == Environment.TESTNET else _PROD_REST

    @classmethod
    def ws_url(cls) -> str:
        if cls.PARADIGM_WS_URL:
            return cls.PARADIGM_WS_URL
        return _TEST_WS if cls.ENVIRONMENT == Environment.TESTNET else _PROD_WS

    @classmethod
    def fspd_base_url(cls) -> str:
        if cls.PARADIGM_FSPD_BASE_URL:
            return cls.PARADIGM_FSPD_BASE_URL.rstrip("/")
        return _TEST_FSPD if cls.ENVIRONMENT == Environment.TESTNET else _PROD_FSPD

    def signer_config_error(self) -> str | None:
        """Name what is missing from the signing proxy settings, or None."""
        if self.PARADIGM_SIGNER_HEADER and not self.PARADIGM_SIGNER_SIGNATURE:
            return "PARADIGM_SIGNER_HEADER also needs PARADIGM_SIGNER_SIGNATURE"
        if self.PARADIGM_SIGNER_SIGNATURE and not self.PARADIGM_SIGNER_HEADER:
            return "PARADIGM_SIGNER_SIGNATURE needs PARADIGM_SIGNER_HEADER"
        if self.PARADIGM_SIGNER_HEADER and self.PARADIGM_SIGNER_HEADER.lower() in _SENT_HEADERS:
            return f"PARADIGM_SIGNER_HEADER cannot be {self.PARADIGM_SIGNER_HEADER}, the server sends it"
        return None

    def is_configured(self) -> bool:
        if self.signer_config_error():
            return False
        return bool(
            self.PARADIGM_ACCESS_KEY and (self.PARADIGM_SIGNING_KEY or self.PARADIGM_SIGNER_HEADER)
        )


_SENT_HEADERS = frozenset(
    {
        "authorization",
        "content-type",
        "paradigm-account",
        "paradigm-api-signature",
        "paradigm-api-timestamp",
    }
)

config = Config()
