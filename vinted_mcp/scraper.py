"""Anonymous client for Vinted's public catalog page.

Vinted has no official API. Until late 2026 `/api/v2/catalog/items` returned JSON
anonymously; that route is now gone (404). The catalog page itself still renders
the same search server-side: the results arrive inside the page as React Server
Component chunks (`self.__next_f.push([1, "..."])`), so we decode those strings
and read the `items` block out of them.

Listing and member pages are server-rendered the same way, so a listing's description,
attributes and photos, and the seller's public profile (reviews, rating, country, last
seen), are read from those pages too.

Read-only (no login, no writes), built for personal price research,
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
_ITEM_ID = re.compile(r"(?:/items/)?(\d{5,})")
_MEMBER_ID = re.compile(r"(?:/member/)?(\d{3,})")


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


# --- listing and seller details -------------------------------------------------

def _stars(reputation: Any, reviews: Any) -> float | None:
    """Vinted stores the rating as 0..1; the site shows it as 0..5 stars. No reviews -> no rating."""
    rep = _to_float(reputation)
    return None if rep is None or not reviews else round(rep * 5, 1)


def _page_blocks(text: str) -> dict[str, dict[str, Any]]:
    """Every item-page block ({"data":…,"name":"description","section":…}), keyed by name.

    The first block of each name wins (the sidebar copy comes before the sticky one).
    """
    dec = json.JSONDecoder()
    blocks: dict[str, dict[str, Any]] = {}
    # Lookahead, not a plain match: blocks nest ({"data":{"data":{…},"name":"favourite"}}).
    for m in re.finditer(r'(?=\{"data":\{)', text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        name = obj.get("name")
        if isinstance(name, str) and isinstance(obj.get("data"), dict):
            blocks.setdefault(name, obj["data"])
    return blocks


def _photo_urls(photos: list[dict[str, Any]] | None) -> list[str]:
    return [p["url"] for p in (photos or []) if p.get("url")]


def parse_item_id(ref: str | int) -> int:
    m = _ITEM_ID.search(str(ref))
    if not m:
        raise ValueError(f"Not a Vinted listing URL or id: {ref!r}")
    return int(m.group(1))


def parse_member_id(ref: str | int) -> int:
    m = _MEMBER_ID.search(str(ref))
    if not m:
        raise ValueError(f"Not a Vinted member URL or id: {ref!r}")
    return int(m.group(1))


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

    def get_listing(self, ref: str | int) -> dict[str, Any]:
        item_id = parse_item_id(ref)
        r = self._client.get(f"{self.base}/items/{item_id}")
        if r.status_code == 404:
            raise RuntimeError(f"Listing {item_id} not found (sold, deleted or hidden)")
        r.raise_for_status()
        b = _page_blocks(_page_payload(r.text))
        if "description" not in b and "attributes" not in b:
            raise RuntimeError("Vinted page layout changed: no listing details found")

        offer = b.get("make_offer") or {}
        attrs = {a.get("code"): (a.get("data") or {}).get("value") for a in (b.get("attributes") or {}).get("attributes", [])}
        status = b.get("ask_seller") or {}
        user = b.get("user_info_header") or {}
        seller_id = user.get("seller_id") or offer.get("seller_id") or status.get("seller_id")
        price = offer.get("price") or {}
        return {
            "id": item_id,
            "title": offer.get("title") or (b.get("gallery") or {}).get("accessibility_label", ""),
            "price": _amount(price),
            "currency": price.get("currency_code") or "EUR",
            "description": (b.get("description") or {}).get("description", ""),
            "brand": attrs.get("brand"),
            "size": attrs.get("size"),
            "condition": attrs.get("status"),
            "colour": attrs.get("color"),
            "uploaded": attrs.get("upload_date"),
            "favourites": (b.get("favourite") or {}).get("favourite_count"),
            "reserved": bool(status.get("is_reserved")),
            "can_buy": bool(status.get("can_buy")),
            "closed": bool((b.get("gallery") or {}).get("is_closed")),
            "photos": _photo_urls((b.get("gallery") or {}).get("photos") or offer.get("photos")),
            "url": str(r.url),
            "seller": {
                "id": int(seller_id) if seller_id else None,
                "username": user.get("name") or (b.get("seller_badges_info") or {}).get("username"),
                "rating_stars": _stars(user.get("feedback_reputation"), user.get("feedback_count")),
                "reviews": user.get("feedback_count"),
                "business": bool(user.get("business")),
                "badges": [x.get("type") for x in (b.get("seller_badges_info") or {}).get("badges", [])],
                "info": [x.get("text") for x in user.get("user_info", []) if x.get("text")],
                "profile_url": f"{self.base}/member/{seller_id}" if seller_id else None,
            },
        }


    def get_seller(self, ref: str | int) -> dict[str, Any]:
        member_id = parse_member_id(ref)
        r = self._client.get(f"{self.base}/member/{member_id}")
        if r.status_code == 404:
            raise RuntimeError(f"Member {member_id} not found")
        r.raise_for_status()
        text = _page_payload(r.text)
        anchor = text.find('"feedback_reputation"')
        start = text.rfind('{"id":%d,' % member_id, 0, anchor) if anchor >= 0 else -1
        if start < 0:
            raise RuntimeError("Vinted page layout changed: no member profile found")
        u, _ = json.JSONDecoder().raw_decode(text, start)
        if u.get("is_deleted"):
            raise RuntimeError(f"Member {member_id} has deleted their account")
        ver = u.get("verification") or {}
        location = ", ".join(x for x in (u.get("city"), u.get("country_title")) if x)
        return {
            "id": u.get("id"),
            "username": u.get("login"),
            "rating_stars": _stars(u.get("feedback_reputation"), u.get("feedback_count")),
            "reviews": u.get("feedback_count"),
            "positive_reviews": u.get("positive_feedback_count"),
            "neutral_reviews": u.get("neutral_feedback_count"),
            "negative_reviews": u.get("negative_feedback_count"),
            "location": location or None,
            "country_code": u.get("country_code"),
            "listings_for_sale": u.get("item_count"),
            "items_sold": u.get("given_item_count"),
            "followers": u.get("followers_count"),
            "last_seen": u.get("last_loged_on_ts"),
            "online_now": bool(u.get("is_online")),
            "on_holiday": bool(u.get("is_on_holiday")),
            "business": bool(u.get("business")),
            "verified": sorted(k for k, v in ver.items() if isinstance(v, dict) and v.get("valid")),
            "bundle_discount": bool((u.get("bundle_discount") or {}).get("enabled")),
            "about": u.get("about") or "",
            "profile_url": u.get("profile_url") or f"{self.base}/member/{member_id}",
        }
