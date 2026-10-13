"""HTTP client for the Paradigm DRFQv2 REST API.

Wraps ``httpx.AsyncClient`` with an auth hook that signs each request
via the configured ``Signer``. Returned bodies are parsed JSON; HTTP
errors are mapped to typed exceptions in ``utils.errors``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from mcp_paradigm.utils.config import config
from mcp_paradigm.utils.errors import raise_for_status
from mcp_paradigm.utils.signing import Signer, get_signer

logger = logging.getLogger(__name__)


def _path_with_query(path: str, params: dict[str, Any] | None) -> str:
    """Build the path-with-query used both for the URL and the signature."""
    if not params:
        return path
    pairs: list[tuple[str, Any]] = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, list | tuple):
            for item in v:
                pairs.append((k, item))
        elif isinstance(v, bool):
            pairs.append((k, "true" if v else "false"))
        else:
            pairs.append((k, v))
    if not pairs:
        return path
    return f"{path}?{urlencode(pairs, doseq=True)}"


class ParadigmClient:
    """Async REST client for ``api.prod.paradigm.co`` / ``api.test.paradigm.co``."""

    def __init__(
        self,
        base_url: str | None = None,
        access_key: str | None = None,
        signer: Signer | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or config.base_url()).rstrip("/")
        self.access_key = access_key or config.PARADIGM_ACCESS_KEY
        if not self.access_key:
            raise ValueError("PARADIGM_ACCESS_KEY is not set.")
        self.signer = signer or get_signer()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or config.REQUEST_TIMEOUT_SECONDS,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ParadigmClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        """Sign and send a single request. Returns parsed JSON (or ``None``).

        ``path`` must start with ``/v2/...`` — it is the path Paradigm
        signs over, with any query string appended in canonical form.
        """
        if not path.startswith("/"):
            path = "/" + path

        signed_path = _path_with_query(path, params)

        if json_body is None:
            body_bytes = b""
            content: bytes | None = None
            headers: dict[str, str] = {}
        else:
            body_bytes = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            content = body_bytes
            headers = {"Content-Type": "application/json"}

        headers["Authorization"] = f"Bearer {self.access_key}"
        headers.update(self.signer.sign(method, signed_path, body_bytes))
        if config.PARADIGM_ACCOUNT:
            headers["Paradigm-Account"] = config.PARADIGM_ACCOUNT

        logger.debug("paradigm %s %s", method, signed_path)
        response = await self._client.request(
            method,
            signed_path,
            content=content,
            headers=headers,
        )

        # Paradigm includes a request id in the response headers; surface
        # it in any error so support / on-call can correlate quickly.
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-paradigm-request-id")
            or response.headers.get("request-id")
        )

        if response.status_code == 204 or not response.content:
            raise_for_status(
                response.status_code,
                None,
                method=method,
                path=signed_path,
                request_id=request_id,
            )
            return None

        try:
            body = response.json()
        except ValueError:
            body = response.text

        raise_for_status(
            response.status_code,
            body,
            method=method,
            path=signed_path,
            request_id=request_id,
        )
        return body

    # Convenience wrappers
    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json_body: Any | None = None) -> Any:
        return await self.request("POST", path, json_body=json_body or {})

    async def put(self, path: str, json_body: Any | None = None) -> Any:
        return await self.request("PUT", path, json_body=json_body or {})

    async def patch(self, path: str, json_body: Any | None = None) -> Any:
        return await self.request("PATCH", path, json_body=json_body or {})

    async def delete(self, path: str, **params: Any) -> Any:
        return await self.request("DELETE", path, params=params)


_singleton: ParadigmClient | None = None
_fspd_singleton: ParadigmClient | None = None
_lock = asyncio.Lock()


async def get_paradigm_client() -> ParadigmClient:
    """Return the process-wide DRFQv2 client singleton."""
    global _singleton
    if _singleton is not None:
        return _singleton
    async with _lock:
        if _singleton is None:
            _singleton = ParadigmClient()
    return _singleton


async def get_fspd_client() -> ParadigmClient:
    """Return the process-wide FSPD (Future Spread) client singleton.

    Same access key + Signer as the DRFQv2 client, but points at the
    FSPD API host (``api.fspd.paradigm.co`` / ``api.fspd.test.paradigm.co``).
    """
    global _fspd_singleton
    if _fspd_singleton is not None:
        return _fspd_singleton
    async with _lock:
        if _fspd_singleton is None:
            _fspd_singleton = ParadigmClient(base_url=config.fspd_base_url())
    return _fspd_singleton
