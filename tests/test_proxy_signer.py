"""Signing through a proxy that holds the key: PARADIGM_SIGNING_DRIVER=proxy."""

from __future__ import annotations

import base64
import logging

import httpx
import pytest

from mcp_paradigm.utils import config as cfg
from mcp_paradigm.utils import paradigm_client
from mcp_paradigm.utils.paradigm_client import ParadigmClient
from mcp_paradigm.utils.signing import EnvKeySigner, ProxySigner, build_message, get_signer
from mcp_paradigm.utils.ws_manager import WSManager

HEADER = "X-Signer-Message"
PLACEHOLDER = "placeholder-signature"


@pytest.fixture
def proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.config, "PARADIGM_SIGNING_KEY", None)
    monkeypatch.setattr(cfg.Config, "SIGNING_DRIVER", "proxy")
    monkeypatch.setattr(cfg.Config, "PARADIGM_SIGNER_HEADER", HEADER)
    monkeypatch.setattr(cfg.Config, "PARADIGM_SIGNER_SIGNATURE", PLACEHOLDER)


def _signed_message(headers: httpx.Headers | dict[str, str]) -> bytes:
    return base64.b64decode(headers[HEADER])


def test_proxy_signer_sends_message_and_placeholder() -> None:
    headers = ProxySigner(HEADER, PLACEHOLDER).sign("POST", "/v2/drfq/orders/", b'{"a":1}')

    ts = headers["Paradigm-API-Timestamp"]
    assert ts.isdigit() and len(ts) >= 13
    assert headers["Paradigm-API-Signature"] == PLACEHOLDER
    assert _signed_message(headers) == build_message(ts, "POST", "/v2/drfq/orders/", b'{"a":1}')


@pytest.mark.usefixtures("proxy_env")
def test_proxy_driver_selects_proxy_signer() -> None:
    assert isinstance(get_signer(), ProxySigner)


@pytest.mark.usefixtures("proxy_env")
def test_signing_key_with_proxy_driver_warns_and_uses_proxy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(cfg.config, "PARADIGM_SIGNING_KEY", base64.b64encode(b"k" * 32).decode())

    with caplog.at_level(logging.WARNING):
        signer = get_signer()

    assert isinstance(signer, ProxySigner)
    assert "PARADIGM_SIGNING_KEY is set" in caplog.text


def test_default_driver_keeps_env_key_signer() -> None:
    assert isinstance(get_signer(), EnvKeySigner)


@pytest.mark.parametrize(
    ("driver", "header", "signature", "missing"),
    [
        ("proxy", HEADER, None, "PARADIGM_SIGNING_DRIVER=proxy needs PARADIGM_SIGNER_SIGNATURE$"),
        ("proxy", None, PLACEHOLDER, "PARADIGM_SIGNING_DRIVER=proxy needs PARADIGM_SIGNER_HEADER$"),
        (
            "env_key",
            HEADER,
            None,
            "PARADIGM_SIGNER_HEADER set without PARADIGM_SIGNING_DRIVER=proxy",
        ),
    ],
)
async def test_bad_signer_config_fails_every_call(
    monkeypatch: pytest.MonkeyPatch,
    driver: str,
    header: str | None,
    signature: str | None,
    missing: str,
) -> None:
    monkeypatch.setattr(cfg.Config, "SIGNING_DRIVER", driver)
    monkeypatch.setattr(cfg.Config, "PARADIGM_SIGNER_HEADER", header)
    monkeypatch.setattr(cfg.Config, "PARADIGM_SIGNER_SIGNATURE", signature)
    monkeypatch.setattr(paradigm_client, "_singleton", None)

    for _ in range(2):
        with pytest.raises(ValueError, match=missing):
            await paradigm_client.get_paradigm_client()


@pytest.mark.usefixtures("proxy_env")
def test_proxy_driver_counts_as_configured_without_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg.Config, "PARADIGM_ACCESS_KEY", "placeholder-access-key")
    monkeypatch.setattr(cfg.Config, "PARADIGM_SIGNING_KEY", None)

    assert cfg.config.is_configured()


@pytest.mark.usefixtures("proxy_env")
@pytest.mark.parametrize(
    ("method", "params", "json_body", "signed_path", "body"),
    [
        (
            "GET",
            {"venue": "DBT", "kind": "OPTION"},
            None,
            "/v2/drfq/rfqs/?venue=DBT&kind=OPTION",
            b"",
        ),
        ("POST", None, {"side": "BUY"}, "/v2/drfq/rfqs/", b'{"side":"BUY"}'),
    ],
)
async def test_rest_request_carries_proxy_headers(
    method: str,
    params: dict[str, str] | None,
    json_body: dict[str, str] | None,
    signed_path: str,
    body: bytes,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    client = ParadigmClient(
        base_url="https://api.test.paradigm.co", access_key="placeholder-access-key"
    )
    client._client = httpx.AsyncClient(
        base_url="https://api.test.paradigm.co", transport=httpx.MockTransport(handler)
    )
    await client.request(method, "/v2/drfq/rfqs/", params=params, json_body=json_body)
    await client.close()

    (request,) = captured
    ts = request.headers["Paradigm-API-Timestamp"]
    assert request.headers["Authorization"] == "Bearer placeholder-access-key"
    assert request.headers["Paradigm-API-Signature"] == PLACEHOLDER
    assert request.url.raw_path.decode() == signed_path
    assert request.content == body
    assert _signed_message(request.headers) == build_message(ts, method, signed_path, body)


@pytest.mark.usefixtures("proxy_env")
def test_ws_handshake_carries_proxy_headers() -> None:
    mgr = WSManager(ws_url="wss://ws.example/v2/drfq/", access_key="placeholder-access-key")

    headers = mgr._handshake_headers()

    ts = headers["Paradigm-API-Timestamp"]
    assert headers["Authorization"] == "Bearer placeholder-access-key"
    assert headers["Paradigm-API-Signature"] == PLACEHOLDER
    assert _signed_message(headers) == build_message(ts, "GET", "/v2/drfq/", b"")
