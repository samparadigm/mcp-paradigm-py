"""Process-wide WebSocket subscription manager for DRFQv2 push streams.

WebSocket events don't map onto request/response tools, so the server
holds a single JSON-RPC-over-WebSocket connection and exposes a
snapshot + tail interface (``subscribe`` / ``poll`` / ``unsubscribe``)
on top of it. Events are buffered in a bounded, TTL-pruned ring so an
MCP client can drain them with ordinary tool calls instead of needing a
bespoke streaming transport.

Protocol (Paradigm DRFQv2 JSON-RPC over WebSocket):

- Connect to ``wss://ws.api.{env}.paradigm.trade/v2/drfq/`` with the
  access key as the ``api-key`` query param and ``cancel_on_disconnect``.
- Subscribe per channel:
  ``{"id": N, "jsonrpc": "2.0", "method": "subscribe",
     "params": {"channel": "<channel>"}}``.
- The client must send a heartbeat at least every 10s or Paradigm closes
  the socket; we send one every 5s.
- Subscriptions then arrive asynchronously as JSON-RPC notifications
  whose ``params`` carry the ``channel`` and the event payload.

The connection is per-process (see DESIGN.md §9): simplest, and matches
how the server already shares one signed REST client. Channels are
reference-counted so the underlying subscribe/unsubscribe is sent once
regardless of how many logical subscriptions a client opens.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

from mcp_paradigm.utils.config import config
from mcp_paradigm.utils.signing import Signer, get_signer

logger = logging.getLogger(__name__)

# Channels the DRFQv2 WebSocket exposes. ``rfq``/``order``/``bbo``/``trade``
# are the high-frequency taker/maker streams; ``trade_confirmation`` and
# ``mmp`` are lower-volume lifecycle events.
CHANNELS = ("rfq", "order", "bbo", "trade", "trade_confirmation", "mmp")

_HEARTBEAT_INTERVAL_SECONDS = 5.0


class WSConnection(Protocol):
    """Minimal async WebSocket surface the manager depends on.

    Satisfied by ``websockets`` client connections; small enough that a
    fake can stand in for it in tests.
    """

    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...


async def _default_connect(url: str, headers: dict[str, str]) -> WSConnection:
    """Open a real WebSocket connection via the ``websockets`` library."""
    from websockets.asyncio.client import connect

    return await connect(url, additional_headers=headers)  # type: ignore[return-value]


class WSManager:
    """Owns one DRFQv2 WebSocket connection and buffers its events."""

    def __init__(
        self,
        *,
        connect_fn: Any = None,
        signer: Signer | None = None,
        ws_url: str | None = None,
        access_key: str | None = None,
        buffer_max: int | None = None,
        buffer_ttl: float | None = None,
    ) -> None:
        self._connect_fn = connect_fn or _default_connect
        self._signer = signer
        self._ws_url = ws_url or config.ws_url()
        self._access_key = access_key or config.PARADIGM_ACCESS_KEY
        self._buffer_max = buffer_max or config.WS_BUFFER_MAX_EVENTS
        self._buffer_ttl = buffer_ttl or config.WS_BUFFER_TTL_SECONDS

        self._conn: WSConnection | None = None
        self._connected = False
        self._reader: asyncio.Task[None] | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

        # sub_id -> {"channel": str, "created_at": float, "cursor": int}
        self._subs: dict[str, dict[str, Any]] = {}
        # channel -> number of live logical subscriptions
        self._channel_refs: dict[str, int] = {}

        self._buffer: deque[dict[str, Any]] = deque(maxlen=self._buffer_max)
        self._seq = 0
        self._rpc_id = 0
        self._cancel_on_disconnect = False

    # -- connection lifecycle -------------------------------------------------

    def _connect_url(self) -> str:
        params = {
            "api-key": self._access_key or "",
            "cancel_on_disconnect": "true" if self._cancel_on_disconnect else "false",
        }
        sep = "&" if "?" in self._ws_url else "?"
        return f"{self._ws_url}{sep}{urlencode(params)}"

    def _handshake_headers(self) -> dict[str, str]:
        """Sign the WS handshake the same way REST requests are signed."""
        if not self._access_key:
            return {}
        signer = self._signer or get_signer()
        path = urlsplit(self._ws_url).path or "/"
        return {
            "Authorization": f"Bearer {self._access_key}",
            **signer.sign("GET", path, b""),
        }

    async def _ensure_connection(self) -> None:
        """Open the connection if needed — reconnecting after a silent drop.

        A dropped socket leaves ``_connected`` False with live channel
        refs; in that case we open a fresh connection and re-send the
        subscribe frames for every channel that still has subscribers so
        existing ``subscription_id``s keep receiving events.
        """
        if self._conn is not None and self._connected:
            return
        resubscribe = bool(self._channel_refs)
        await self._close_connection()
        url = self._connect_url()
        logger.info("opening DRFQv2 WebSocket connection")
        conn = await self._connect_fn(url, self._handshake_headers())
        self._conn = conn
        self._connected = True
        self._reader = asyncio.create_task(self._read_loop(conn))
        self._heartbeat = asyncio.create_task(self._heartbeat_loop())
        if resubscribe:
            for channel in list(self._channel_refs):
                await self._send_rpc("subscribe", {"channel": channel})

    async def _close_connection(self) -> None:
        """Tear down the socket + background tasks, keeping subs/buffer.

        Used both for a full teardown (last unsubscribe) and to discard a
        stale connection before reconnecting.
        """
        self._connected = False
        for task in (self._reader, self._heartbeat):
            if task is not None:
                task.cancel()
        self._reader = None
        self._heartbeat = None
        if self._conn is not None:
            with contextlib.suppress(Exception):  # best-effort close
                await self._conn.close()
        self._conn = None

    async def _next_rpc_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    async def _send(self, payload: dict[str, Any]) -> None:
        assert self._conn is not None
        await self._conn.send(json.dumps(payload))

    async def _send_rpc(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC request frame with an auto-incrementing id."""
        frame: dict[str, Any] = {
            "id": await self._next_rpc_id(),
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            frame["params"] = params
        await self._send(frame)

    # -- background loops -----------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            try:
                await self._send_rpc("heartbeat")
            except Exception as exc:  # pragma: no cover - connection dropped
                logger.warning("heartbeat failed, WebSocket likely dropped: %s", exc)
                self._connected = False
                return

    async def _read_loop(self, conn: WSConnection) -> None:
        try:
            while True:
                raw = await conn.recv()
                self._ingest(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - connection dropped
            logger.warning("WebSocket read loop ended: %s", exc)
        finally:
            # Flag the drop so the next subscribe reconnects — but only if
            # this is still the live connection (not a deliberate teardown
            # that already swapped in a new socket).
            if conn is self._conn:
                self._connected = False

    def _ingest(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(msg, dict):
            return
        params = msg.get("params")
        # JSON-RPC notifications carry the channel + payload under params;
        # request acks carry a top-level "id"/"result" and are ignored.
        if not isinstance(params, dict):
            return
        channel = params.get("channel")
        if not isinstance(channel, str):
            return
        self._seq += 1
        self._buffer.append(
            {
                "seq": self._seq,
                "channel": channel,
                "received_at": time.time(),
                "data": params.get("data", params),
            }
        )

    # -- buffer maintenance ---------------------------------------------------

    def _prune_expired(self) -> None:
        cutoff = time.time() - self._buffer_ttl
        while self._buffer and self._buffer[0]["received_at"] < cutoff:
            self._buffer.popleft()

    # -- public API -----------------------------------------------------------

    async def subscribe(
        self, channel: str, *, cancel_on_disconnect: bool = False
    ) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; valid channels: {', '.join(CHANNELS)}")
        async with self._lock:
            if not self._channel_refs:
                # cancel_on_disconnect is a connection-level setting; it can
                # only be chosen by the subscribe that opens the socket.
                self._cancel_on_disconnect = cancel_on_disconnect
            await self._ensure_connection()

            refs = self._channel_refs.get(channel, 0)
            if refs == 0:
                await self._send_rpc("subscribe", {"channel": channel})
            self._channel_refs[channel] = refs + 1

            sub_id = uuid.uuid4().hex
            self._subs[sub_id] = {
                "channel": channel,
                "created_at": time.time(),
                # Start the tail at the current head: poll only returns
                # events that arrive after the subscription opens.
                "cursor": self._seq,
            }
        return {
            "subscription_id": sub_id,
            "channel": channel,
            "cancel_on_disconnect": self._cancel_on_disconnect,
        }

    async def poll(
        self, subscription_id: str, *, since: int | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        sub = self._subs.get(subscription_id)
        if sub is None:
            raise ValueError(
                f"unknown subscription_id {subscription_id!r} "
                "(it may have been unsubscribed, or never opened)."
            )
        self._prune_expired()
        after = since if since is not None else sub["cursor"]
        channel = sub["channel"]
        events = [e for e in self._buffer if e["channel"] == channel and e["seq"] > after]
        if limit is not None:
            events = events[:limit]
        # Advance the stored cursor so the next poll without `since`
        # continues where this one left off.
        cursor = events[-1]["seq"] if events else after
        sub["cursor"] = cursor
        return {
            "subscription_id": subscription_id,
            "channel": channel,
            "events": events,
            "cursor": cursor,
            "connected": self._connected,
        }

    async def unsubscribe(self, subscription_id: str) -> dict[str, Any]:
        async with self._lock:
            sub = self._subs.pop(subscription_id, None)
            if sub is None:
                raise ValueError(f"unknown subscription_id {subscription_id!r} (already closed?).")
            channel = sub["channel"]
            remaining = self._channel_refs.get(channel, 0) - 1
            if remaining <= 0:
                self._channel_refs.pop(channel, None)
                if self._conn is not None and self._connected:
                    try:
                        await self._send_rpc("unsubscribe", {"channel": channel})
                    except Exception as exc:  # pragma: no cover - already dropped
                        logger.warning("unsubscribe send failed: %s", exc)
            else:
                self._channel_refs[channel] = remaining

            # No logical subscriptions left → drop the connection so we
            # don't hold an idle socket (and any cancel-on-disconnect with it).
            if not self._subs:
                await self._close_connection()
        return {"subscription_id": subscription_id, "channel": channel, "closed": True}


_manager: WSManager | None = None
_manager_lock = asyncio.Lock()


async def get_ws_manager() -> WSManager:
    """Return the process-wide WebSocket subscription manager singleton."""
    global _manager
    if _manager is not None:
        return _manager
    async with _manager_lock:
        if _manager is None:
            _manager = WSManager()
    return _manager
