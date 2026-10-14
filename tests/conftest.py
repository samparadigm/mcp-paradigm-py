"""Shared pytest fixtures."""

from __future__ import annotations

import base64
import os

import pytest


@pytest.fixture(autouse=True)
def _paradigm_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a deterministic signing key + access key for the test session.

    Integration tests (``@pytest.mark.integration``) opt out so they run
    against the real credentials in the environment instead of the fakes.
    """
    if request.node.get_closest_marker("integration"):
        return
    key_b64 = base64.b64encode(b"k" * 32).decode("ascii")
    monkeypatch.setenv("PARADIGM_ACCESS_KEY", "ak_test")
    monkeypatch.setenv("PARADIGM_SIGNING_KEY", key_b64)
    monkeypatch.setenv("PARADIGM_ENVIRONMENT", "testnet")

    from mcp_paradigm.utils import config as cfg

    monkeypatch.setattr(cfg.config, "PARADIGM_ACCESS_KEY", "ak_test")
    monkeypatch.setattr(cfg.config, "PARADIGM_SIGNING_KEY", key_b64)
    monkeypatch.setattr(cfg.config, "ENVIRONMENT", "testnet")
    monkeypatch.setattr(cfg.Config, "SIGNING_DRIVER", "env_key")
    monkeypatch.setattr(cfg.Config, "PARADIGM_SIGNER_HEADER", None)
    monkeypatch.setattr(cfg.Config, "PARADIGM_SIGNER_SIGNATURE", None)
