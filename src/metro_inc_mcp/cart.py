"""Account cart operations. All calls need a logged-in session (see auth.py).

The tools take product codes; entry numbers are looked up from a fresh cart read before each change.
"""

from __future__ import annotations

import json
import logging
import re

from .auth import AuthManager, page_is_authenticated
from .client import GroceryClient
from .config import Language
from .errors import AuthExpired, GroceryError, NoServiceContext, UpstreamError
from .models import (
    AddedItem,
    AddToCartResult,
    Cart,
    CartItem,
    CartLine,
    ClearCartResult,
    RemoveResult,
    UpdatedLine,
)
from .parsing.cart import parse_cart_page, parse_csrf
from .parsing.service import parse_service_context

log = logging.getLogger(__name__)

_CODE = re.compile(r"^\d{1,14}$")
JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


class ProductNotInCart(GroceryError):
    def __init__(self, code: str) -> None:
        super().__init__(f"Product {code} is not in the cart. Call view_cart to see the product codes in it.")


class InvalidProductCode(GroceryError):
    def __init__(self, code: str) -> None:
        super().__init__(f"{code!r} is not a product code (expected digits, e.g. '055872026016' or '4011').")


def _check_code(code: str) -> str:
    code = code.strip()
    if not _CODE.match(code):
        raise InvalidProductCode(code)
    return code


def _out_of_stock(line: CartLine) -> str:
    return (f"{line.code} ({line.name}) is out of stock at the pickup store: the cart line has no price "
            "and the product may be missing from the order.")


def _add_warnings(item: AddedItem, line: CartLine | None) -> list[str]:
    """Warnings for one added product, from the add response and the cart line read right after."""
    if line is not None:
        item.quantity_in_cart = line.quantity
        item.available = line.available
    warnings = []
    if item.status != "success":
        limit = f" (limit {line.max_qty} per order)" if line and line.max_qty else ""
        if item.status == "maxOrderQuantityExceeded":
            in_cart = f", the cart has {item.quantity_in_cart}" if item.quantity_in_cart is not None else ""
            warnings.append(f"{item.code}: quantity limit reached{limit}{in_cart}.")
        else:
            warnings.append(f"{item.code}: the site answered '{item.status}'{limit}.")
    if line is not None and line.available is False:
        warnings.append(_out_of_stock(line))
    return warnings


class CartService:
    def __init__(self, client: GroceryClient, auth: AuthManager) -> None:
        self.client = client
        self.auth = auth

    @property
    def _path(self) -> str:
        """Write endpoints (entries) use the banner's primary language path (French on Super C / Metro)."""
        return self.client.settings.write_paths.cart

    async def _cart_html(self, language: Language) -> str:
        path = self.client.settings.paths(language).cart
        await self.auth.ensure_logged_in()
        html = await self.client.get_text(path)
        if page_is_authenticated(html) is False:  # server session expired: log in again once
            log.info("session expired, logging in again")
            self.auth.mark_logged_out()
            await self.auth.ensure_logged_in()
            html = await self.client.get_text(path)
            if page_is_authenticated(html) is False:
                raise AuthExpired()
        return html

    async def view(self, language: Language | None = None) -> Cart:
        lang = self.client.settings.resolve_language(language)
        html = await self._cart_html(lang)
        cart = parse_cart_page(html, lang)
        cart.service = parse_service_context(html)
        return cart

    async def _line(self, code: str) -> CartLine:
        cart = await self.view()
        for line in cart.lines:
            if line.code == code:
                return line
        raise ProductNotInCart(code)

    async def _send(self, method: str, path: str, payload: object | None, headers: dict[str, str] | None = None):
        """JSON AJAX call (no body when payload is None). On 409, tell apart 'logged out' from 'no store selected'."""
        await self.auth.ensure_logged_in()
        body = {} if payload is None else {"data": json.dumps(payload)}
        for attempt in (1, 2):
            resp = await self.client.request(method, path, ajax=True, headers={**JSON_HEADERS, **(headers or {})},
                                             **body)
            if resp.status_code != 409:
                break
            html = await self.client.get_text(self._path)
            if page_is_authenticated(html) is not False or attempt == 2:
                raise NoServiceContext()
            self.auth.mark_logged_out()
            await self.auth.ensure_logged_in()
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, path)
        return resp

    async def add(self, items: list[CartItem]) -> AddToCartResult:
        payload = [{"productCode": _check_code(i.product_code), "quantity": i.quantity} for i in items]
        resp = await self._send("POST", f"{self._path}/entries", payload)
        data = resp.json()
        entries = data.get("entries") or []
        requested = [p["quantity"] for p in payload] if len(entries) == len(payload) else [None] * len(entries)
        added = [
            AddedItem(code=str(e.get("sku")), status=str(e.get("status")), requested_quantity=req,
                      # quantity is -1 when nothing could be added; the cart read below fills it in
                      quantity_in_cart=e.get("quantity") if (e.get("quantity") or 0) >= 0 else None,
                      entry_number=e.get("entryNumber"))
            for e, req in zip(entries, requested)
        ]
        try:  # stock and limits are only visible on the cart page
            lines = {line.code: line for line in (await self.view()).lines}
        except GroceryError as e:
            log.warning("cart read after add failed: %s", e)
            lines = {}
        warnings = [w for item in added for w in _add_warnings(item, lines.get(item.code))]
        return AddToCartResult(added=added, item_count=data.get("numberOfItems"), warnings=warnings,
                               messages=[str(m) for m in data.get("messages") or []])

    async def update_quantity(self, code: str, quantity: int) -> UpdatedLine:
        code = _check_code(code)
        line = await self._line(code)
        substitution = "NO" if line.substitution_allowed is False else "YES"
        await self._send("PATCH", f"{self._path}/entries/{line.entry_number}",
                         {"quantity": quantity, "productCode": code, "substitutionPermission": substitution})
        line = await self._line(code)
        warnings = []
        if line.quantity != quantity:
            # The site caps a PATCH at the product's max quantity without any error.
            limit = f" (limit {line.max_qty} per order)" if line.max_qty else ""
            warnings.append(f"{code}: asked for {quantity}, the cart has {line.quantity}{limit}.")
        if line.available is False:
            warnings.append(_out_of_stock(line))
        return UpdatedLine(**line.model_dump(), requested_quantity=quantity, warnings=warnings)

    async def remove(self, code: str) -> RemoveResult:
        code = _check_code(code)
        line = await self._line(code)
        resp = await self._send("DELETE", f"{self._path}/entries/{line.entry_number}", {"productCode": code})
        data = resp.json()
        return RemoveResult(removed_code=code, item_count=data.get("cartNbItems"), cart_empty=data.get("isCartEmpty"))

    async def clear(self) -> ClearCartResult:
        """Remove every line in one call, like the site's 'Vider mon panier' button (DELETE <cart>/entries/all).

        The site's JS sends the X-CSRF-TOKEN from <meta name="_csrf">: Metro needs it (403 without, verified
        2026-11-09); Super C and Jean Coutu have no such tag and accept the call without it.
        Returns what was removed, so the assistant can add it back.
        """
        lang = self.client.settings.banner.primary_language
        html = await self._cart_html(lang)
        before = parse_cart_page(html, lang)
        removed = [CartItem(product_code=line.code, quantity=line.quantity) for line in before.lines]
        if not removed:
            return ClearCartResult(removed=[], item_count=0, cart_empty=True)
        await self._send("DELETE", f"{self._path}/entries/all", None, headers=parse_csrf(html))
        after = await self.view()
        return ClearCartResult(removed=removed, removed_names={line.code: line.name for line in before.lines},
                               item_count=after.item_count, cart_empty=not after.lines)
