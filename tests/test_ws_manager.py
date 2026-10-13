"""Tests for the DRFQv2 WebSocket subscription manager.

A fake connection stands in for the real ``websockets`` client so we can
drive the subscribe / poll / unsubscribe lifecycle deterministically and
assert the JSON-RPC frames the manager emits.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from mcp_paradigm.utils.ws_manager import CHANNELS, WSManager


class _FakeSigner:
    def sign(self, _method: str, _path: str, _body_bytes: bytes) -> dict[str, str]:
        return {
            "Paradigm-API-Timestamp": "1700000000000",
            "Paradigm-API-Signature": "fake-signature",
        }


class _FakeConn:
    """In-memory WebSocket double: records sends, replays fed messages."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True

    def feed(self, payload: dict[str, Any]) -> None:
        self._queue.put_nowait(json.dumps(payload))

    def methods(self) -> list[str]:
        return [m.get("method") for m in self.sent]


def _make_manager() -> tuple[WSManager, _FakeConn]:
    conn = _FakeConn()

    async def connect_fn(url: str, headers: dict[str, str]) -> _FakeConn:
        connect_fn.url = url  # type: ignore[attr-defined]
        connect_fn.headers = headers  # type: ignore[attr-defined]
        return conn

    mgr = WSManager(
        connect_fn=connect_fn,
        signer=_FakeSigner(),
        ws_url="wss://ws.example/v2/drfq/",
        access_key="ak_test",
    )
    mgr._connect_fn_ref = connect_fn  # type: ignore[attr-defined]
    return mgr, conn


async def _drain() -> None:
    """Let the reader task process anything queued."""
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_subscribe_opens_connection_and_sends_frame() -> None:
    mgr, conn = _make_manager()
    res = await mgr.subscribe("rfq")

    assert res["channel"] == "rfq"
    assert res["subscription_id"]
    assert res["cancel_on_disconnect"] is False
    assert "subscribe" in conn.methods()
    sub_frame = next(f for f in conn.sent if f.get("method") == "subscribe")
    assert sub_frame["params"] == {"channel": "rfq"}
    assert sub_frame["jsonrpc"] == "2.0"

    # Handshake URL carries api-key + cancel_on_disconnect.
    url = mgr._connect_fn_ref.url  # type: ignore[attr-defined]
    assert "api-key=ak_test" in url
    assert "cancel_on_disconnect=false" in url
    headers = mgr._connect_fn_ref.headers  # type: ignore[attr-defined]
    assert headers["Authorization"] == "Bearer ak_test"
    assert headers["Paradigm-API-Signature"] == "fake-signature"

    await mgr.unsubscribe(res["subscription_id"])


@pytest.mark.asyncio
async def test_unknown_channel_rejected() -> None:
    mgr, _ = _make_manager()
    with pytest.raises(ValueError, match="unknown channel"):
        await mgr.subscribe("not-a-channel")


@pytest.mark.asyncio
async def test_poll_returns_only_subscribed_channel_after_cursor() -> None:
    mgr, conn = _make_manager()
    sub = await mgr.subscribe("rfq")
    sub_id = sub["subscription_id"]

    conn.feed(
        {
            "jsonrpc": "2.0",
            "method": "subscription",
            "params": {"channel": "order", "data": {"id": "o1"}},
        }
    )
    conn.feed(
        {
            "jsonrpc": "2.0",
            "method": "subscription",
            "params": {"channel": "rfq", "data": {"id": "r1"}},
        }
    )
    conn.feed(
        {
            "jsonrpc": "2.0",
            "method": "subscription",
            "params": {"channel": "rfq", "data": {"id": "r2"}},
        }
    )
    await _drain()

    out = await mgr.poll(sub_id)
    ids = [e["data"]["id"] for e in out["events"]]
    assert ids == ["r1", "r2"]  # the "order" event is filtered out
    assert all(e["channel"] == "rfq" for e in out["events"])
    assert out["cursor"] == out["events"][-1]["seq"]

    # Cursor advanced — a second poll with no new events is empty.
    again = await mgr.poll(sub_id)
    assert again["events"] == []
    assert again["cursor"] == out["cursor"]

    await mgr.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_poll_limit_and_since() -> None:
    mgr, conn = _make_manager()
    sub = await mgr.subscribe("trade")
    sub_id = sub["subscription_id"]
    for i in range(5):
        conn.feed({"method": "subscription", "params": {"channel": "trade", "data": {"n": i}}})
    await _drain()

    first = await mgr.poll(sub_id, limit=2)
    assert [e["data"]["n"] for e in first["events"]] == [0, 1]

    rest = await mgr.poll(sub_id, since=first["cursor"])
    assert [e["data"]["n"] for e in rest["events"]] == [2, 3, 4]

    await mgr.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_channel_refcount_single_subscribe_unsubscribe() -> None:
    mgr, conn = _make_manager()
    a = await mgr.subscribe("bbo")
    b = await mgr.subscribe("bbo")
    # Subscribed to the same channel twice → only one protocol subscribe.
    assert conn.methods().count("subscribe") == 1

    await mgr.unsubscribe(a["subscription_id"])
    # One logical sub remains → no unsubscribe frame yet, connection alive.
    assert "unsubscribe" not in conn.methods()
    assert conn.closed is False

    await mgr.unsubscribe(b["subscription_id"])
    # Last sub gone → unsubscribe sent and connection torn down.
    assert "unsubscribe" in conn.methods()
    assert conn.closed is True


@pytest.mark.asyncio
async def test_poll_unknown_subscription_raises() -> None:
    mgr, _ = _make_manager()
    with pytest.raises(ValueError, match="unknown subscription_id"):
        await mgr.poll("does-not-exist")


@pytest.mark.asyncio
async def test_cancel_on_disconnect_propagates_to_url() -> None:
    mgr, _ = _make_manager()
    sub = await mgr.subscribe("rfq", cancel_on_disconnect=True)
    assert sub["cancel_on_disconnect"] is True
    assert "cancel_on_disconnect=true" in mgr._connect_fn_ref.url  # type: ignore[attr-defined]
    await mgr.unsubscribe(sub["subscription_id"])


def test_channels_constant_matches_documented_set() -> None:
    assert CHANNELS == ("rfq", "order", "bbo", "trade", "trade_confirmation", "mmp")


class _DroppingConn(_FakeConn):
    """A fake whose recv() raises once the fed queue drains, simulating a drop."""

    async def recv(self) -> str:
        if self._queue.empty():
            raise ConnectionError("socket dropped")
        return await self._queue.get()


@pytest.mark.asyncio
async def test_silent_drop_marks_disconnected_and_reconnects() -> None:
    conns: list[_FakeConn] = []

    async def connect_fn(url: str, headers: dict[str, str]) -> _FakeConn:
        # First socket drops on first recv; the reconnect gets a healthy
        # socket whose recv() blocks (stays connected).
        conn: _FakeConn = _DroppingConn() if not conns else _FakeConn()
        conns.append(conn)
        return conn

    mgr = WSManager(
        connect_fn=connect_fn,
        signer=_FakeSigner(),
        ws_url="wss://ws.example/v2/drfq/",
        access_key="ak_test",
    )

    sub = await mgr.subscribe("rfq")
    await _drain()  # let the first conn's recv() drain → ConnectionError → drop

    # poll surfaces the drop honestly rather than reporting connected.
    out = await mgr.poll(sub["subscription_id"])
    assert out["connected"] is False

    # Subscribing again reconnects on a fresh socket and re-sends the
    # subscribe frame for the still-live channel.
    sub2 = await mgr.subscribe("rfq")
    assert len(conns) == 2
    assert "subscribe" in conns[1].methods()
    resub = next(f for f in conns[1].sent if f.get("method") == "subscribe")
    assert resub["params"] == {"channel": "rfq"}

    again = await mgr.poll(sub["subscription_id"])
    assert again["connected"] is True

    await mgr.unsubscribe(sub["subscription_id"])
    await mgr.unsubscribe(sub2["subscription_id"])
