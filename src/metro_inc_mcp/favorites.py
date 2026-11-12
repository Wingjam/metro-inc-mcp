"""The account's favorites list ("Mes favoris", called "cart starter" in the site's code).

Endpoints, under `SitePaths.favorites` (e.g. `/cart-starter`, `/magasiner/cart-starter` on Jean Coutu):
- `GET  getFavorites`: HTML fragment of product tiles (Jean Coutu: 404, the list is read from the account page
  `SitePaths.favorites_list`),
- `POST addToCartStarter` with the add-to-cart JSON `[{"productCode", "quantity"}]`: 204,
- `POST deleteProduct/<product code>`, no body: 204.

The list is not consistent across the site's servers (Super C, 2026-11-11): a session sticks to one copy, and about
1 session in 4 kept showing favorites deleted the day before, for at least 25 minutes. Deletes sent from such a
session answered 204 without changing that copy. So results never re-read the list to confirm a change.
"""

from __future__ import annotations

import json

from .auth import AuthManager, page_is_authenticated
from .cart import _check_code
from .client import GroceryClient
from .config import Language
from .errors import AuthExpired, UpstreamError
from .models import FavoriteList, FavoritesChange
from .parsing.cart import parse_csrf
from .parsing.products import parse_favorites

DELAY_NOTE = ("The site keeps several copies of the favorites list that are not always in sync: a recent change may "
              "not show in view_favorites, and a removed favorite may still appear for a while.")


class FavoritesService:
    def __init__(self, client: GroceryClient, auth: AuthManager) -> None:
        self.client = client
        self.auth = auth

    async def _csrf(self) -> dict[str, str]:
        """CSRF header from the cart page when the banner has one (Metro), else {}. Also checks the session."""
        await self.auth.ensure_logged_in()
        cart_path = self.client.settings.write_paths.cart
        html = await self.client.get_text(cart_path)
        if page_is_authenticated(html) is False:
            self.auth.mark_logged_out()
            await self.auth.ensure_logged_in()
            html = await self.client.get_text(cart_path)
            if page_is_authenticated(html) is False:
                raise AuthExpired()
        return parse_csrf(html)

    async def view(self, language: Language | None = None) -> FavoriteList:
        lang = self.client.settings.resolve_language(language)
        await self._csrf()  # makes sure the session is logged in: an anonymous session has no favorites
        paths = self.client.settings.paths(lang)
        html = await self.client.get_text(paths.favorites_list_path(), ajax=not paths.favorites_list)
        return FavoriteList(language=lang, favorites=parse_favorites(html, self.client.base_url),
                            note=DELAY_NOTE)

    async def _post(self, path: str, headers: dict[str, str], data: str | None = None) -> None:
        kwargs = {"data": data} if data is not None else {}
        resp = await self.client.request("POST", path, ajax=True,
                                         headers={"Content-Type": "application/json; charset=utf-8", **headers},
                                         **kwargs)
        if resp.status_code not in (200, 204):
            raise UpstreamError(resp.status_code, path)

    async def add(self, codes: list[str], quantity: int = 1) -> FavoritesChange:
        codes = list(dict.fromkeys(_check_code(c) for c in codes))
        prefix = self.client.settings.write_paths.favorites
        await self._post(f"{prefix}/addToCartStarter", await self._csrf(),
                         json.dumps([{"productCode": c, "quantity": quantity} for c in codes]))
        return FavoritesChange(changed=codes, note=DELAY_NOTE)

    async def remove(self, code: str) -> FavoritesChange:
        code = _check_code(code)
        prefix = self.client.settings.write_paths.favorites
        await self._post(f"{prefix}/deleteProduct/{code}", await self._csrf())
        return FavoritesChange(changed=[code], note=DELAY_NOTE)
