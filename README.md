# vinted-mcp

<!-- mcp-name: io.github.ThiagoJacobLannes/vinted-mcp -->

MCP server for searching second-hand listings on [Vinted](https://www.vinted.pt/), so Claude (or any MCP client) can answer "what does a used X go for?".

**Anonymous and read-only.** No login, no account, no writes: it only searches. Not affiliated with Vinted.

## Tool

### `search`
Search listings, with optional filters. Returns the total number of matches and the listings for one page.

Parameters:
- `query` — search keywords (e.g. `"nike air max 90"`, `"vestido zara"`)
- `price_min` / `price_max` — price range in EUR
- `sort` — `"relevance"` (default) | `"cheap"` | `"expensive"` | `"newest"`
- `page` — page number (default 1)
- `per_page` — results per page (default 24, max 96)

Each listing has: title, price, price with Vinted's buyer protection fee (shipping is extra), brand, size, condition, link, photo, whether the seller is a business, and favourites.

Tip: `"cheap"` also pulls in loosely related listings. For "the cheapest X", use the default relevance sort with `price_max`.

## Install

**Quickest** (needs [uv](https://docs.astral.sh/uv/)): no clone needed, it runs straight from PyPI.

```bash
claude mcp add vinted -- uvx vinted-search-mcp
```

For Claude Desktop, use `"command": "uvx", "args": ["vinted-search-mcp"]`.

**From source:**

Requires Python 3.10+.

```bash
git clone https://github.com/ThiagoJacobLannes/vinted-mcp
cd vinted-mcp
python -m pip install -e .
```

On Windows, if you keep code in a cloud-synced folder (Google Drive, OneDrive), create the virtual environment **outside** it: sync clients drop `desktop.ini` files into folders, which can crash packages on startup.

## Add to Claude Code

```bash
claude mcp add vinted -- python -m vinted_mcp.server
```

## Add to Claude Desktop

Merge `claude_desktop_config.snippet.json` into your Claude Desktop `claude_desktop_config.json`, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "vinted": {
      "command": "python",
      "args": ["-m", "vinted_mcp.server"]
    }
  }
}
```

## Other countries

Portugal is the default. Set `VINTED_BASE_URL` to another Vinted domain (for example `https://www.vinted.fr` or `https://www.vinted.es`) to search there.

## How it works

Vinted has no official API. The server loads Vinted's public catalog page for your search and reads the results the page already contains (they arrive as React Server Component data). If Vinted changes its page, the tool fails with a clear `{"error": ...}` instead of returning wrong data.

## License

MIT
