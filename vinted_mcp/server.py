"""FastMCP stdio server exposing anonymous Vinted (PT) search, listing details and seller profiles — read-only."""

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


@mcp.tool()
def get_listing(listing: str, include_seller_profile: bool = True) -> dict[str, Any]:
    """Full details of one Vinted listing: description, brand, size, condition, colour,
    upload time, all photos, favourites, whether it is reserved, and who sells it
    (username, star rating, number of reviews, last online).

    Use it after `search` to look closer at a listing, or on a Vinted link the user pastes.

    Args:
        listing:                A listing URL (https://www.vinted.pt/items/123…) or its id.
        include_seller_profile: Also open the seller's profile (one more page) and add
                                positive/neutral/negative reviews, country, items sold,
                                listings for sale, followers, verifications and their bio.
    """
    try:
        c = client()
        item = c.get_listing(listing)
        if include_seller_profile and item["seller"]["id"]:
            try:
                item["seller"] = c.get_seller(item["seller"]["id"]) | {
                    "info": item["seller"]["info"],
                    "badges": item["seller"]["badges"],
                }
            except Exception as exc:  # noqa: BLE001 — keep the listing even if the profile fails
                log.warning("seller profile failed: %s", exc)
                item["seller"]["profile_error"] = str(exc)
        return item
    except Exception as exc:  # noqa: BLE001
        log.exception("get_listing failed")
        return {"error": str(exc)}


@mcp.tool()
def get_seller(seller: str) -> dict[str, Any]:
    """A Vinted member's public profile: star rating, positive/neutral/negative reviews,
    country, items sold, listings for sale, followers, last seen, verifications
    (email, Facebook, Google…), holiday mode and their bio.

    Args:
        seller: A profile URL (https://www.vinted.pt/member/123…) or the member id
                (the `seller.id` returned by get_listing).
    """
    try:
        return client().get_seller(seller)
    except Exception as exc:  # noqa: BLE001
        log.exception("get_seller failed")
        return {"error": str(exc)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
