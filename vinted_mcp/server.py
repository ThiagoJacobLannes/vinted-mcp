"""FastMCP stdio server exposing anonymous Vinted (PT) search — read-only."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .scraper import BASE_URL, VintedClient

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s vinted-mcp %(levelname)s %(message)s",
)
log = logging.getLogger("vinted_mcp")

mcp = FastMCP("vinted")

_client: VintedClient | None = None


def client() -> VintedClient:
    global _client
    if _client is None:
        _client = VintedClient(os.environ.get("VINTED_BASE_URL", BASE_URL))
    return _client


@mcp.tool()
def search(
    query: str,
    price_min: float | None = None,
    price_max: float | None = None,
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 24,
) -> dict[str, Any]:
    """Search second-hand listings on Vinted (Portugal by default; anonymous, read-only).

    Good for "what does a used X go for on Vinted?" price research. Prices are what the
    seller asks; total_with_buyer_protection adds Vinted's buyer fee (shipping is extra).

    Args:
        query:     Search keywords, e.g. "nike air max 90", "vestido zara".
        price_min: Minimum price in EUR.
        price_max: Maximum price in EUR.
        sort:      "relevance" (default) | "cheap" | "expensive" | "newest".
                   "cheap" also pulls in loosely related listings; for "the cheapest X",
                   prefer relevance with price_max.
        page:      Results page (default 1).
        per_page:  Results per page (default 24, max 96).
    """
    try:
        res = client().search(
            query,
            price_min=price_min,
            price_max=price_max,
            order=sort,
            page=page,
            per_page=per_page,
        )
        return {
            "total_results": res.total,
            "page": res.page,
            "count": len(res.items),
            "items": [
                {
                    "title": it.title,
                    "price": it.price,
                    "total_with_buyer_protection": it.total_price,
                    "currency": it.currency,
                    "brand": it.brand,
                    "size": it.size,
                    "condition": it.status,
                    "url": it.url,
                    "image_url": it.photo_url,
                    "business_seller": it.business_seller,
                    "favourites": it.favourites,
                    "id": it.id,
                }
                for it in res.items
            ],
        }
    except Exception as exc:  # noqa: BLE001 — surface a clean message to the model
        log.exception("search failed")
        return {"error": str(exc)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
