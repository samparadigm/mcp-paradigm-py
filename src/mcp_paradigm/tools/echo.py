"""Echo / signing self-test tool."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_paradigm.server.server import server
from mcp_paradigm.utils.paradigm_client import get_paradigm_client


@server.tool(
    name="paradigm_echo",
    title="Echo",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def paradigm_echo(
    payload: Annotated[
        dict[str, Any] | None,
        Field(description="Optional JSON object to round-trip. None ⇒ GET /echo."),
    ] = None,
) -> Any:
    """Round-trip a payload through Paradigm's echo endpoint.

    The first call you should make after wiring up the server: a 200
    response confirms your access key, signing key, and base URL are
    all correct. GET form has no body; POST echoes back the payload.
    """
    client = await get_paradigm_client()
    if payload is None:
        return await client.get("/v2/drfq/echo/")
    return await client.post("/v2/drfq/echo/", json_body=payload)
