# Contributing

Thanks for your interest in `mcp-paradigm-py`.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/) (recommended)
or pip, plus [just](https://just.systems) for the dev commands.

```bash
git clone https://github.com/tradeparadigm/mcp-paradigm-py.git
cd mcp-paradigm-py
just install-dev      # pip install -e ".[dev]" + pre-commit install
cp .env.template .env
# fill in PARADIGM_ACCESS_KEY and PARADIGM_SIGNING_KEY
```

## Dev loop

```bash
just check            # format + lint + test
just test             # pytest only
just format           # ruff format
just lint             # ruff check --fix
just run              # python -m mcp_paradigm (stdio)
just mcpb             # build .mcpb bundle for Claude Desktop
```

`just --list` shows everything.

## Code quality

- **ruff** — formatter + linter (config in `pyproject.toml`).
- **pre-commit** — runs ruff and basic hygiene checks on every commit.
- **pytest** + **respx** — unit tests with httpx MockTransport. No live
  network in the default test run.

## Tests

```bash
just test             # all unit tests
just test-cov         # coverage report to htmlcov/
```

Integration tests against `api.testnet.paradigm.trade` are gated behind
`@pytest.mark.integration` and skipped by default. Run with
`pytest -m integration` once you have testnet credentials.

## Adding a tool

1. Add the implementation under `src/mcp_paradigm/tools/<module>.py`.
2. Register it with `@server.tool(...)`.
3. Import the module in `src/mcp_paradigm/tools/__init__.py` so the
   decorator runs at server startup.
4. Add to `manifest.json` so MCPB-installed instances see it.
5. Add a unit test in `tests/`.

For destructive tools (anything that puts money on the wire), use
`ToolAnnotations(destructiveHint=True)` so MCP clients prompt for
approval before execution.

## Releasing

Releases are cut from `main`. The `publish` workflow runs on a GitHub
Release `published` event and:

1. Builds sdist + wheel, publishes to PyPI via Trusted Publishing (OIDC).
2. Builds the MCPB bundle (`.mcpb`) and attaches it to the release.
3. Installs the published wheel from PyPI and smoke-tests it.

Bump `version` in `pyproject.toml`, `manifest.json`, `server.json`, and
`src/mcp_paradigm/__init__.py` in the same PR, then tag the release.

## Project structure

```
src/mcp_paradigm/
├── server/server.py      # FastMCP entrypoint, CLI
├── tools/                # MCP tools, grouped by responsibility
│   ├── echo.py
│   ├── reference_data.py
│   ├── rfqs.py
│   ├── orders.py
│   ├── trades.py
│   ├── pricing.py
│   └── mmp.py
└── utils/
    ├── config.py         # env-driven config
    ├── errors.py         # typed exceptions
    ├── signing.py        # Signer protocol + EnvKeySigner
    └── paradigm_client.py
```

See [DESIGN.md](DESIGN.md) for the full architecture.
