"""MCP server definition: thin tool wrappers around the catalog / cart / service modules."""

from __future__ import annotations

import logging
import sys
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import catalog
from .auth import AuthManager
from .cart import CartService
from .client import GroceryClient
from .config import Language, Settings
from .errors import GroceryError
from .models import (
    AddToCartResult,
    Cart,
    CartItem,
    QuickSearchResult,
    RemoveResult,
    SearchResult,
    SetStoreResult,
    StoreList,
    TimeslotList,
    UpdatedLine,
)
from .service_context import ServiceContextService

_BANNER = Settings.from_env().banner
_SITE = _BANNER.base_url.removeprefix("https://www.")

if len(_BANNER.languages) > 1:
    _LANGUAGE_HINT = """\
Language: the site exists in French and English. Every read tool takes an optional `language`
('fr' or 'en'). Use the user's language: search with English terms and language='en' for an
English-speaking user, French terms and language='fr' otherwise. Product codes, store ids and
slot ids are the same in both languages."""
else:
    _LANGUAGE_HINT = f"""\
Language: this site exists only in '{_BANNER.primary_language}'. Search with terms in that language;
the `language` argument is ignored."""

_KIND_HINT = (
    "- This is a pharmacy: the online store sells over-the-counter health, beauty and household products, "
    "not prescriptions. Pickup stores are named after the owner pharmacist; use the address to tell them apart. "
    "Pickup has no timeslot." if _BANNER.kind == "pharmacy" else ""
)

INSTRUCTIONS = f"""\
Unofficial access to the {_BANNER.name} ({_SITE}) {_BANNER.kind} website, on the user's own account.
{_BANNER.name} is a Metro inc. banner; this server handles only this banner and its cart.
{_LANGUAGE_HINT}
{_KIND_HINT}
- Use quick_search to find one specific product (fast, top 3 results with prices).
- Use search_products to browse or compare (about 42 products per page).
- Cart tools use product codes from search results. add_to_cart takes several products at once.
- Products sold by weight (is_weighted / approximate) are added by count (units or trays); the price is an estimate.
- view_cart shows the pickup store. If an add fails because no store is chosen, use find_stores then
  set_pickup_store (ask the user first: it changes the store for the whole cart, which can change prices).
- get_timeslots only reads available pickup times; booking a timeslot is not supported yet.
- Checkout and payment are not supported: the user completes the order on {_SITE}.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
IDEMPOTENT_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                   open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

mcp = MCPServer(_BANNER.key, title=f"{_BANNER.name} (unofficial)", instructions=INSTRUCTIONS)


class _State:
    client: GroceryClient | None = None
    auth: AuthManager | None = None
    cart: CartService | None = None
    service: ServiceContextService | None = None


def get_client() -> GroceryClient:
    if _State.client is None:
        _State.client = GroceryClient(Settings.from_env())
    return _State.client


def _auth() -> AuthManager:
    if _State.auth is None:
        client = get_client()
        _State.auth = AuthManager(client, client.settings.cookies_file)
    return _State.auth


def get_cart() -> CartService:
    if _State.cart is None:
        _State.cart = CartService(get_client(), _auth())
    return _State.cart


def get_service() -> ServiceContextService:
    if _State.service is None:
        _State.service = ServiceContextService(get_client(), _auth())
    return _State.service


ProductCode = Annotated[str, Field(description="Product code from a search result or view_cart, e.g. '055872026016'")]
Lang = Annotated[Language | None, Field(description="'fr' or 'en'. Defaults to METRO_LANGUAGE.")]
PostalCode = Annotated[str, Field(description="Canadian postal code, e.g. 'H2X 1Y4'")]
StoreId = Annotated[str, Field(description="Store id from find_stores, e.g. '274'")]


@mcp.tool(annotations=READ_ONLY)
async def quick_search(
    query: Annotated[str, Field(description="Product to find, e.g. 'beurre salé' (fr) or 'salted butter' (en)")],
    language: Lang = None,
) -> QuickSearchResult:
    """Find a specific product: returns the top 3 matches with prices, suggested terms and the total count."""
    try:
        return await catalog.quick_search(get_client(), query, language)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=READ_ONLY)
async def search_products(
    query: Annotated[str, Field(description="Search terms, e.g. 'lait' (fr) or 'milk' (en)")],
    page: Annotated[int, Field(ge=1, le=50, description="Result page, about 42 products per page")] = 1,
    language: Lang = None,
) -> SearchResult:
    """Full product search with prices, regular prices for items on sale, sizes and unit prices."""
    try:
        return await catalog.search_products(get_client(), query, page, language)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=READ_ONLY)
async def view_cart(language: Lang = None) -> Cart:
    """Show the user's cart: lines with product codes, quantities, prices, estimated total and pickup store."""
    try:
        return await get_cart().view(language)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=WRITE)
async def add_to_cart(
    items: Annotated[list[CartItem], Field(min_length=1, max_length=50, description="Products and quantities")],
) -> AddToCartResult:
    """Add products to the cart. Adding a product already in the cart increases its quantity.

    The site may add less than asked (limit per order) and accepts out-of-stock products:
    check `warnings` and tell the user.
    """
    try:
        return await get_cart().add(items)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=IDEMPOTENT_WRITE)
async def update_cart_quantity(
    product_code: ProductCode,
    quantity: Annotated[int, Field(ge=1, le=99, description="New total quantity (use remove_from_cart for 0)")],
) -> UpdatedLine:
    """Set the quantity of a product already in the cart.

    The site silently caps the quantity at the product's limit per order: check `warnings` and tell the user.
    """
    try:
        return await get_cart().update_quantity(product_code, quantity)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=DESTRUCTIVE)
async def remove_from_cart(product_code: ProductCode) -> RemoveResult:
    """Remove a product from the cart."""
    try:
        return await get_cart().remove(product_code)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=READ_ONLY)
async def find_stores(postal_code: PostalCode, language: Lang = None) -> StoreList:
    """List the banner's stores offering pickup near a postal code, nearest first."""
    try:
        return await get_service().find_stores(postal_code, language)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=READ_ONLY)
async def get_timeslots(store_id: StoreId, postal_code: PostalCode, language: Lang = None) -> TimeslotList:
    """Pickup days and timeslots of a store (status AVAILABLE / FULL / NO_TIMESLOT, fee per slot). Read only."""
    try:
        return await get_service().get_timeslots(store_id, postal_code, language)
    except GroceryError as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=IDEMPOTENT_WRITE)
async def set_pickup_store(store_id: StoreId, postal_code: PostalCode) -> SetStoreResult:
    """Choose the pickup store for the user's cart, without booking a timeslot.

    This changes the store for the whole cart: assortment and prices follow that store.
    Confirm with the user before calling it.
    """
    try:
        return await get_service().set_pickup_store(store_id, postal_code)
    except GroceryError as e:
        raise ToolError(str(e)) from e


def run() -> None:
    settings = Settings.from_env()
    logging.basicConfig(stream=sys.stderr, level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mcp.run("stdio")
