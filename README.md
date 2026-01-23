# RationSmart MCP Server

MCP server that exposes RationSmart tools for onboarding, cow profiles, and diet generation.

## Features

- MCP JSON-RPC endpoint at `POST /mcp` (supports SSE when `Accept: text/event-stream`).
- Optional REST helpers: `GET /health`, `GET /tools`, `POST /tools/call`.
- Namespaced tool names (e.g., `rationsmart.cows.create`) with backward-compatible aliases.

## Requirements

- Python 3.11+
- Backend API access with a service API key

## Configuration

Set environment variables:

- `RATIONSMART_BACKEND_URL` (e.g., `https://<backend-host>`)
- `RATIONSMART_API_KEY` (service API key)
- `PORT` (optional, default: `8080`)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
PORT=8080 python -m src.server
```

## MCP Examples

Initialize:

```bash
curl -sS http://<host>/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{"protocolVersion":"2024-11-05"}}'
```

List tools:

```bash
curl -sS http://<host>/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"2","method":"tools/list","params":{}}'
```

Call a tool:

```bash
curl -sS http://<host>/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"3","method":"tools/call","params":{"name":"rationsmart.cows.list","arguments":{"device_id":"<uuid>"}}}'
```

## Tool Naming

Tools use the `rationsmart.<resource>.<action>` namespace. Legacy tool names
(`get_countries`, `list_cows`, etc.) are still accepted as aliases for
compatibility.

