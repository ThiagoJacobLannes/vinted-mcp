"""Anonymous client for Vinted's public catalog page.

Vinted has no official API. Until late 2026 `/api/v2/catalog/items` returned JSON
anonymously; that route is now gone (404). The catalog page itself still renders
the same search server-side: the results arrive inside the page as React Server
Component chunks (`self.__next_f.push([1, "..."])`), so we decode those strings
and read the `items` block out of them.

Read-only and search-only (no login, no writes), built for personal price research,
modelled on kuantokusta-mcp.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("vinted_mcp")

# Portugal by default. Each country has its own domain (vinted.fr, vinted.es…); VINTED_BASE_URL overrides it.
BASE_URL = "https://www.vinted.pt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}

# Friendly sort names -> Vinted's `order` values.
ORDER_MAP = {
    "relevance": "relevance",
    "cheap": "price_low_to_high",
    "expensive": "price_high_to_low",
    "newest": "newest_first",
}

# One streamed chunk: self.__next_f.push([1,"<a JS string>"])
_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_ITEMS_KEY = '"items":{"items":['


def _to_float(v: Any) -> float | None:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _amount(price: dict[str, Any] | None) -> float | None:
    return _to_float((price or {}).get("amount"))


@dataclass
class VintedItem:
    id: int | None
    title: str
    price: float | None          # what the seller asks
    total_price: float | None    # what the buyer pays: price + buyer protection fee (shipping not included)
    currency: str
    brand: str
    size: str
    status: str                  # condition, e.g. "Muito bom estado"
    url: str
    photo_url: str
    business_seller: bool
    favourites: int | None


@dataclass
class SearchResult:
    total: int | None
    page: int
    items: list[VintedItem]


def _page_payload(html: str) -> str:
    """Decode every streamed chunk and join them into one text."""
    parts = []
    for m in _CHUNK.finditer(html):
        try:
            parts.append(json.loads('"' + m.group(1) + '"'))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def _extract_items_block(html: str) -> dict[str, Any]:
    text = _page_payload(html)
    at = text.find(_ITEMS_KEY)
    if at < 0:
        raise RuntimeError("Vinted page layout changed: no items block found")
    block, _ = json.JSONDecoder().raw_decode(text, at + len('"items":'))
    return block


def _split_second_line(line: str) -> tuple[str, str]:
    """'42 · Muito bom' -> ('42', 'Muito bom'); 'Novo com etiquetas' -> ('', 'Novo com etiquetas')."""
    bits = [b.strip() for b in (line or "").split("·") if b.strip()]
    if len(bits) >= 2:
        return bits[0], " · ".join(bits[1:])
    return "", bits[0] if bits else ""


class VintedClient:
    """Keeps one httpx session so Vinted's anonymous cookies are reused across calls."""

    def __init__(self, base: str = BASE_URL) -> None:
        self.base = base.rstrip("/")
        self._client = httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True)

    def search(
        self,
        query: str,
        price_min: float | None = None,
        price_max: float | None = None,
        order: str = "relevance",
        page: int = 1,
        per_page: int = 24,
        currency: str = "EUR",
    ) -> SearchResult:
        params: dict[str, Any] = {
            "search_text": query,
            "page": max(1, int(page)),
            "order": ORDER_MAP.get(order, "relevance"),
            "currency": currency,
        }
        if price_min is not None:
            params["price_from"] = price_min
        if price_max is not None:
            params["price_to"] = price_max

        r = self._client.get(self.base + "/catalog", params=params)
        r.raise_for_status()
        block = _extract_items_block(r.text)

        items: list[VintedItem] = []
        for row in block.get("items", []):
            it = row.get("productItem") or {}
            box = it.get("itemBox") or {}
            size, status = _split_second_line(box.get("secondLine", ""))
            items.append(
                VintedItem(
                    id=it.get("id"),
                    title=it.get("title", "") or "",
                    price=_amount(it.get("priceWithDiscount") or it.get("price")),
                    total_price=_amount(it.get("totalItemPrice")),
                    currency=(it.get("price") or {}).get("currencyCode") or currency,
                    brand=box.get("firstLine", "") or "",
                    size=size,
                    status=status,
                    url=self.base + (it.get("url") or ""),
                    photo_url=it.get("thumbnailUrl", "") or "",
                    business_seller=bool((it.get("user") or {}).get("isBusiness")),
                    favourites=it.get("favouriteCount"),
                )
            )
        # The page always returns its own page size (96); the tool trims to what was asked for.
        items = items[: max(1, min(int(per_page), 96))]
        pagination = block.get("pagination") or {}
        return SearchResult(total=pagination.get("total_entries"), page=params["page"], items=items)
