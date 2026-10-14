# Quickstart

Get the Paradigm MCP server running against testnet in under two minutes.

## 1. Install

```bash
pip install mcp-paradigm
# or, for local development:
git clone https://github.com/tradeparadigm/mcp-paradigm-py.git
cd mcp-paradigm-py
just install-dev
```

## 2. Get credentials

Mint an access key + signing key from the Paradigm admin UI. You need:

- **Access key** — sent as `Authorization: Bearer <access_key>`.
- **Signing key** — base64-encoded HMAC-SHA256 key. Used to sign every
  outbound request. **Keep this secret.**

For first-time wiring use the testnet environment
(`api.testnet.paradigm.trade`).

## 3. Configure

```bash
export PARADIGM_ACCESS_KEY="..."
export PARADIGM_SIGNING_KEY="..."   # base64 string
export PARADIGM_ENVIRONMENT="testnet"
```

To sign through a signing proxy, leave `PARADIGM_SIGNING_KEY` out and set
`PARADIGM_SIGNING_DRIVER=proxy`, `PARADIGM_SIGNER_HEADER` and `PARADIGM_SIGNER_SIGNATURE`. See
[Signing proxy](../README.md#signing-proxy-no-signing-key) in the README.

Or copy `.env.template` to `.env` and fill in the same values —
`python-dotenv` will load them at import.

## 4. Smoke test

```bash
mcp-paradigm   # boots on stdio
```

In another shell, use any MCP client (or the `mcp` CLI) to call
`paradigm_echo` first. A 200 response means signing is correct.

## 5. Wire into Claude Desktop / Claude Code

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

Or install the prebuilt `.mcpb` bundle from the latest
[GitHub release](https://github.com/tradeparadigm/mcp-paradigm-py/releases)
— Claude Desktop will prompt you for the access key + signing key on
first run.

## 6. First workflow

A typical DRFQv2 taker flow:

```
paradigm_desk_overview                       # positions, MMP, platform state
paradigm_drfqv2_counterparties venue=PRDX    # which LPs can quote this venue?
paradigm_drfqv2_instruments venue=DBT        # find what's tradable
paradigm_drfqv2_create_rfq …                 # ⚠ approval prompt (broadcast by default)
paradigm_drfqv2_rfq_snapshot rfq_id=…        # RFQ + BBO + orders as quotes arrive
paradigm_drfqv2_post_order …                 # ⚠ approval prompt (cross to trade)
paradigm_drfqv2_trades trade_id=…            # confirm settlement
```

Prefer the workflow tools — `paradigm_desk_overview`,
`paradigm_drfqv2_rfq_snapshot` — over wiring the individual GETs yourself.
For live quotes instead of polling, use `paradigm_subscribe('bbo')` →
`paradigm_poll(subscription_id)` → `paradigm_unsubscribe`.

`paradigm_drfqv2_create_rfq`, `paradigm_drfqv2_post_order`,
`paradigm_drfqv2_cancel`, `paradigm_drfqv2_mmp(action='reset')`, and
`paradigm_kill_switch` are annotated `destructiveHint=true` — MCP clients
should display an approval prompt before invoking them.
