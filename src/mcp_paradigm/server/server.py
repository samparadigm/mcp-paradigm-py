"""FastMCP server entry point for the Paradigm trading platform."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp.server import FastMCP

from mcp_paradigm import __version__
from mcp_paradigm.utils.config import config

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp-paradigm")


def create_server() -> FastMCP:
    """Build the FastMCP server instance with description and metadata."""
    return FastMCP(
        name=config.SERVER_NAME,
        instructions=f"""Paradigm MCP Server v{__version__} — DRFQv2, OBv1, FSPD.

Workflow tools are the recommended entry points. Per-product tools
are kept for granular control.

Start with:
• paradigm_echo                       — verify signing is wired up
• paradigm_desk_overview              — positions, MMP, platform state across all products
• paradigm_drfqv2_rfq_snapshot(id)    — full DRFQv2 RFQ state in one call
• paradigm_obv1_market_snapshot(id)   — full OBv1 market state in one call
• paradigm_kill_switch                — cancel everything across all products (destructive)

Per-product (DRFQv2 bilateral RFQ): paradigm_drfqv2_{{rfqs, orders,
post_order, cancel, trades, instruments, counterparties, price_legs,
mmp, create_rfq}}.

Live data (DRFQv2 WebSocket): paradigm_subscribe(channel) →
paradigm_poll(subscription_id) → paradigm_unsubscribe. Channels: rfq,
order, bbo, trade, trade_confirmation, mmp. Use instead of REST polling.

Per-product (OBv1 order books): paradigm_obv1_{{obs, create_ob,
quotes, post_quote, cancel, orders, trades, instruments, price_legs,
mmp}}.

Per-product (FSPD future spreads): paradigm_fspd_{{instruments,
strategies, orderbook, orders, post_order, cancel, trades, venues,
system, mmp}}.

Firm-level (cross-product): paradigm_identity_credentials,
paradigm_positions, paradigm_leaderboard, paradigm_leaderboard_preferences.

Prompts (workflow playbooks): quote_rfq, broadcast_rfq, stream_and_tail.

Conventions: list-and-single are merged (pass `*_id` to fetch one);
MMP status+reset are merged (`action` param); post/replace and
post/update are merged (pass the id to amend). Tools annotated
destructive prompt for user approval in MCP clients.""",
    )


server = create_server()


# Register tools. Imports run their module-level decorators which attach
# tools to the singleton `server`. F401-safe; see tools/__init__.py.
import mcp_paradigm.tools


def run_cli() -> None:
    """CLI entry point declared in pyproject.toml."""
    parser = argparse.ArgumentParser(description="MCP Paradigm Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport (default: stdio) [env: MCP_TRANSPORT]",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", str(config.SERVER_PORT))),
        help=f"Port for streamable-http (default: {config.SERVER_PORT}) [env: MCP_PORT]",
    )
    args = parser.parse_args()

    signer_error = config.signer_config_error()
    if signer_error:
        logger.warning("%s; tools that call the Paradigm API will fail.", signer_error)
    elif not config.is_configured():
        logger.warning(
            "Set PARADIGM_ACCESS_KEY and either PARADIGM_SIGNING_KEY or the signing proxy "
            "settings; tools that call the Paradigm API will fail until then."
        )

    logger.info("Starting MCP Paradigm server (transport=%s)", args.transport)
    try:
        if args.transport == "streamable-http":
            server.settings.port = args.port
            server.settings.host = "0.0.0.0"
            server.run(transport="streamable-http")
        else:
            server.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as exc:  # pragma: no cover
        logger.exception("Server crashed: %s", exc)
        sys.exit(1)


__all__ = ["create_server", "run_cli", "server"]
