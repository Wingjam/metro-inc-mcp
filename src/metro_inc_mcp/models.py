"""Structured tool outputs."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class Product(BaseModel):
    code: str = Field(description="Product code (UPC or PLU). Use it to add the product to the cart.")
    name: str
    brand: str | None = None
    size: str | None = Field(None, description="Package size as shown on the site, e.g. '4 L', '450 mL'")
    price: Decimal | None = Field(None, description="Current shelf price in CAD")
    price_text: str | None = Field(None, description="Price as displayed, e.g. '0,49 $ env. ch.' or '4,99 $ch.'")
    regular_price: Decimal | None = Field(None, description="Regular price when the product is on sale")
    on_sale: bool = False
    unit_price: str | None = Field(None, description="Price per unit of measure, e.g. '0,22 $ /100 ml'")
    is_weighted: bool = Field(False, description="Sold by approximate weight; quantity is a count, final price varies")
    min_qty: int | None = None
    max_qty: int | None = None
    category: str | None = None
    url: str | None = None


class SearchResult(BaseModel):
    query: str
    language: str = Field(description="Language of names and prices: 'fr' or 'en'")
    page: int
    total: int | None = Field(None, description="Total number of matching products")
    products: list[Product]


class CartLine(BaseModel):
    entry_number: int
    code: str
    name: str
    brand: str | None = None
    size: str | None = None
    quantity: int
    price: Decimal | None = Field(None, description="Price per unit (per item or per tray)")
    price_text: str | None = Field(None, description="Price as displayed; 'env.' means approximate (sold by weight)")
    on_sale: bool = False
    line_total: Decimal | None = Field(None, description="Line subtotal; approximate for items sold by weight")
    approximate: bool = Field(False, description="Final price depends on the weight picked in store")
    substitution_allowed: bool | None = None
    max_qty: int | None = Field(None, description="Maximum quantity per order for this product")
    available: bool | None = Field(
        None, description="False: out of stock at the pickup store. The line has no price and may be missing "
                          "from the order.")


class UpdatedLine(CartLine):
    requested_quantity: int
    warnings: list[str] = Field(default_factory=list, description="Tell the user about these")


class PriceLine(BaseModel):
    description: str
    amount: Decimal | None = None
    text: str | None = None


class Cart(BaseModel):
    language: str = Field("fr", description="Language of names and labels: 'fr' or 'en'")
    item_count: int | None = Field(None, description="Number of items (sum of quantities)")
    lines: list[CartLine]
    subtotal: Decimal | None = None
    estimated_total: Decimal | None = None
    price_lines: list[PriceLine] = Field(default_factory=list, description="Summary lines (subtotal, fees, ...)")
    minimum_order_reached: bool | None = None
    service: ServiceContext | None = Field(None, description="Pickup store / delivery chosen for this cart")


class CartItem(BaseModel):
    product_code: str = Field(description="Product code from a search result")
    quantity: int = Field(1, ge=1, le=99, description="Number of units (or trays for items sold by weight)")


class AddedItem(BaseModel):
    code: str
    status: str = Field(description="'success' when added as requested, e.g. 'maxOrderQuantityExceeded' otherwise")
    requested_quantity: int | None = Field(None, description="Quantity asked for in this call")
    quantity_in_cart: int | None = Field(None, description="Total quantity of this product in the cart now")
    entry_number: int | None = None
    available: bool | None = Field(None, description="False: out of stock at the pickup store")


class AddToCartResult(BaseModel):
    added: list[AddedItem]
    item_count: int | None = Field(None, description="Items in the cart after the add")
    warnings: list[str] = Field(default_factory=list,
                                description="Quantity limits and out-of-stock products: tell the user about these")
    messages: list[str] = Field(default_factory=list, description="Messages from the site, as displayed")


class RemoveResult(BaseModel):
    removed_code: str
    item_count: int | None = None
    cart_empty: bool | None = None


class Store(BaseModel):
    store_id: str = Field(description="Store id to pass to get_timeslots / set_pickup_store")
    name: str
    address: str | None = None


class StoreList(BaseModel):
    postal_code: str
    stores: list[Store] = Field(description="Pickup stores near the postal code, nearest first")


class Timeslot(BaseModel):
    slot_id: str
    start: str = Field(description="ISO 8601 start, e.g. 2026-11-09T12:00-05:00")
    end: str
    label: str | None = Field(None, description="As displayed, e.g. '12h-13h' or '12PM-1PM'")
    price: Decimal | None = Field(None, description="Fee in CAD, 0 when free")
    price_text: str | None = None
    available: bool = True


class Day(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    label: str | None = Field(None, description="As displayed, e.g. 'Demain' / 'Tomorrow'")
    status: str | None = Field(None, description="AVAILABLE, FULL or NO_TIMESLOT")
    slots: list[Timeslot] = Field(default_factory=list)


class TimeslotList(BaseModel):
    store_id: str
    store_name: str | None = None
    service_point_id: str | None = None
    language: str
    days: list[Day]
    note: str | None = None


class ServiceContext(BaseModel):
    service_type: str | None = Field(None, description="PICK_UP_IN_STORE or HOME_DELIVERY")
    store_id: str | None = None
    store_name: str | None = None
    store_address: str | None = None
    timeslot_selected: bool | None = None


class SetStoreResult(BaseModel):
    store_id: str
    store_name: str | None = Field(None, description="Store name confirmed by the site")
    service_type: str | None = None
    store_changed: bool | None = None
    timeslot: str | None = Field(None, description="Timeslot shown by the site after the change")


class QuickSearchResult(BaseModel):
    query: str
    language: str = Field(description="Language of names and prices: 'fr' or 'en'")
    total: int | None = None
    suggestions: list[str] = Field(default_factory=list, description="Suggested search terms")
    products: list[Product] = Field(description="Top 3 products")
