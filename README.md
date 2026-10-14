# mcp-paradigm-py

<!-- mcp-name: io.github.tradeparadigm/mcp-paradigm-py -->

MCP server for the **Paradigm** trading platform. Exposes the REST
surface as typed tools to any MCP client (Claude Code, Claude Desktop,
any IDE with MCP support).

Covers the active Paradigm products:

- **DRFQv2** — bilateral RFQ (request-for-quote)
- **OBv1** — Unified Markets order books (long-lived multi-counterparty
  auctions; maker quotes, taker fills, block trades, trade tape)
- **FSPD** — Future Spread Direct (orderbook for future spreads with
  market/limit orders, post-only, IOC, order replace)
- **Firm** — identity credentials, positions, cross-firm leaderboards

GRFQ is being deprecated in favour of OBv1; VRFQ is niche. Neither is
covered.

> See [`DESIGN.md`](DESIGN.md) for the full design — tool surface,
> auth model, signing layer, deployment posture.

## Install

```bash
# from PyPI
pip install mcp-paradigm

# or one-shot via uvx (no install)
uvx mcp-paradigm

# or for local development
git clone https://github.com/tradeparadigm/mcp-paradigm-py.git
cd mcp-paradigm-py
just install-dev
```

Claude Desktop users: install the prebuilt `.mcpb` bundle from the
latest [GitHub release](https://github.com/tradeparadigm/mcp-paradigm-py/releases)
— double-click to install, then enter your access key + signing key
when prompted.

## Configure

Set your Paradigm access key and signing key. The signing key is
base64-encoded as issued by Paradigm.

```bash
# Required, unless you sign through a signing proxy (below):
export PARADIGM_ACCESS_KEY="..."         # bearer token (access key id)
export PARADIGM_SIGNING_KEY="..."        # base64-encoded HMAC key

# Optional (sensible defaults; only set if you need to override):
export PARADIGM_ENVIRONMENT="testnet"    # "prod" (default) or "testnet"
# export PARADIGM_BASE_URL="https://api.testnet.paradigm.trade"
# export PARADIGM_WS_URL="wss://ws.api.testnet.paradigm.trade/v2/drfq/"
# export PARADIGM_ACCOUNT="my-desk"      # if running multi-desk
```

### Signing proxy (no signing key)

To sign through a proxy that holds the signing key, set
`PARADIGM_SIGNING_DRIVER=proxy` and these two, and leave `PARADIGM_SIGNING_KEY` unset:

- `PARADIGM_SIGNER_HEADER`: the header the server puts each signing message in, base64
- `PARADIGM_SIGNER_SIGNATURE`: the placeholder the server sends as
  `Paradigm-API-Signature`, for the proxy to replace

Every tool call fails while either is missing, or while either is set with
another driver. If `PARADIGM_SIGNING_KEY` is also set, the server logs a warning
and uses the proxy.

We wrote this for iron-proxy, the signing proxy DIME Terminal runs in front of
its agents. Another proxy has to do what iron-proxy does with these headers.
For example, with `PARADIGM_SIGNING_DRIVER=proxy` and
`PARADIGM_SIGNER_HEADER=X-Dime-Sign-paradigm-mainnet-signing`,
the server sends:

```
Paradigm-API-Timestamp: 1760000000000
Paradigm-API-Signature: <PARADIGM_SIGNER_SIGNATURE>
X-Dime-Sign-paradigm-mainnet-signing: base64("1760000000000\nGET\n/v2/drfq/rfqs/\n")
```

iron-proxy decodes `X-Dime-Sign-<label>`, signs it with HMAC-SHA256 using the key
it holds for that label, swaps the base64 result in for the placeholder, and
deletes the `X-Dime-Sign-<label>` header before forwarding the request.

## Run

```bash
# stdio transport — for Claude Desktop / Claude Code
mcp-paradigm

# streamable-http — for remote agents
mcp-paradigm --transport streamable-http --port 3000
```

### Wiring into Claude Code / Desktop

```json
{
  "mcpServers": {
    "paradigm": {
      "command": "mcp-paradigm",
      "env": {
        "PARADIGM_ACCESS_KEY": "...",
        "PARADIGM_SIGNING_KEY": "...",
        "PARADIGM_ENVIRONMENT": "testnet"
      }
    }
  }
}
```

## Smoke test

After wiring up the server, call `paradigm_echo` first. A 200 response
confirms your access key, signing key, and environment are all correct.
If signing is broken you'll see a 401 with `Invalid signature`.

## Tool surface

43 tools, workflow-oriented. Full mapping in [DESIGN.md](DESIGN.md).

### Start here

| Tool | What it does |
|---|---|
| `paradigm_echo` | Signing self-test — first call after wiring. |
| `paradigm_desk_overview` | Positions + MMP + platform state across all products in one call. |
| `paradigm_drfqv2_rfq_snapshot(rfq_id)` | RFQ + BBO + order book for a DRFQv2 RFQ. |
| `paradigm_obv1_market_snapshot(ob_id)` | OB + BBO + quotes book for an OBv1 market. |
| `paradigm_kill_switch` | Cancel all orders/quotes across all products. **Destructive.** |

### Per-product (granular)

| Product | Tools |
|---|---|
| DRFQv2 | `paradigm_drfqv2_{rfqs, create_rfq, orders, post_order, cancel, trades, instruments, counterparties, price_legs, mmp}` |
| Streaming (DRFQv2 WS) | `paradigm_subscribe`, `paradigm_poll`, `paradigm_unsubscribe` |
| OBv1 | `paradigm_obv1_{obs, create_ob, quotes, post_quote, cancel, orders, trades, instruments, price_legs, mmp}` |
| FSPD | `paradigm_fspd_{instruments, strategies, orderbook, orders, post_order, cancel, trades, venues, system, mmp}` |
| Firm | `paradigm_identity_credentials`, `paradigm_positions`, `paradigm_leaderboard`, `paradigm_leaderboard_preferences` |

### Prompts

Canned workflow playbooks clients can surface in a menu — they guide the
tool sequence without executing it: `quote_rfq` (maker), `broadcast_rfq`
(taker), `stream_and_tail` (consume a live WebSocket channel).

### Conventions

- List and single-fetch share one tool — pass `{resource}_id` to fetch one.
- MMP status + reset share one tool — `action='status'|'reset'`.
- Post and amend share one tool — pass `*_id` to switch to PUT/replace.
- Cancel is unified per product (single id or batch by filter).
- Destructive tools (`*_post_order`, `*_post_quote`, `*_create_*`,
  `*_cancel`, `*_mmp(action='reset')`, `paradigm_kill_switch`) are
  annotated `destructiveHint=true` so MCP clients prompt for approval.

## Development

```bash
just check       # format + lint + test
just test        # pytest only
just mcpb        # build .mcpb bundle for Claude Desktop
just build       # sdist + wheel
just docker      # docker build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full dev loop.

Signing is verified by `tests/test_signing.py` against the canonical
Paradigm message layout (`<timestamp>\n<METHOD>\n<path-with-query>\n<body>`).

## Streaming

For live data, `paradigm_subscribe(channel)` opens a DRFQv2 WebSocket
stream (`rfq`, `order`, `bbo`, `trade`, `trade_confirmation`, `mmp`) and
returns a `subscription_id`. Drain events with
`paradigm_poll(subscription_id)` — each carries a monotonic `seq` and the
cursor advances automatically — and close with
`paradigm_unsubscribe(subscription_id)`. The server holds one shared,
heartbeated connection and buffers events (bounded by `PARADIGM_WS_BUFFER`
/ `PARADIGM_WS_TTL`), so quotes push in rather than needing REST polling.

## Status

Alpha. REST and DRFQv2 WebSocket streaming are complete; production
signers (Vault Transit, AWS KMS) are tracked in DESIGN.md.

## License

MIT — see [LICENSE](LICENSE).
