"""Service panel pages (service-choice, service-timeslot) and the cart's current service context.

The ids and data-* attributes are the same in French and English; only labels differ.
"""

from __future__ import annotations

import re
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser, LexborNode

from ..models import Day, ServiceContext, Store, Timeslot
from .prices import clean_text, parse_amount

PICKUP = "pick_up_in_store"
_FREE = re.compile(r"^(gratuit|free)$", re.IGNORECASE)
_DATE_CLASS = re.compile(rf"service-{PICKUP}-(\d{{4}}-\d{{2}}-\d{{2}})")


def parse_store_list(html: str, pickup_only: bool = False) -> list[Store]:
    """Stores in page order (nearest first).

    Grocery banners: the service-choice page. With pickup_only (Jean Coutu, from service-timeslot):
    only stores with a pickup service point, which leaves out the delivery-only entries.
    """
    tree = LexborHTMLParser(html)
    stores: dict[str, Store] = {}
    selector = "[data-store-id][data-store-name][data-pickup-service-point-id]" if pickup_only \
        else "[data-store-id][data-store-name]"
    for n in tree.css(selector):
        a = n.attributes
        sid = a.get("data-store-id") or ""
        if sid and sid not in stores:
            stores[sid] = Store(store_id=sid, name=clean_text(a.get("data-store-name")) or sid,
                                address=clean_text(a.get("data-store-address")))
    return list(stores.values())


def parse_form_state(html: str) -> str | None:
    node = LexborHTMLParser(html).css_first(".st--main[data-form-state-id]")
    return node.attributes.get("data-form-state-id") if node else None


def parse_pickup_point(html: str, store_id: str) -> tuple[str | None, str | None]:
    """(service_point_id, store_name) of a pickup store listed in service-timeslot."""
    tree = LexborHTMLParser(html)
    for n in tree.css(f'[data-store-id="{store_id}"][data-pickup-service-point-id]'):
        return n.attributes.get("data-pickup-service-point-id"), clean_text(n.attributes.get("data-store-name"))
    return None, None


def _ancestor_store(node: LexborNode) -> str | None:
    n = node.parent
    while n is not None:
        if "data-store-id" in n.attributes:
            return n.attributes.get("data-store-id")
        n = n.parent
    return None


def _slot(radio: LexborNode) -> Timeslot:
    a = radio.attributes
    li = radio.parent
    while li is not None and li.tag != "li":
        li = li.parent
    title = li.css_first(".timeslot--title") if li is not None else None
    price_node = li.css_first(".timeslot-price") if li is not None else None
    price_text = clean_text(price_node.text(separator=" ")) if price_node else None
    price = Decimal(0) if price_text and _FREE.match(price_text) else parse_amount(price_text)
    status = li.attributes.get("data-timeslot-status") if li is not None else None
    return Timeslot(
        slot_id=a.get("slot-id") or "",
        start=a.get("slot-from") or "",
        end=a.get("slot-to") or "",
        label=clean_text(title.text(separator=" ")) if title else None,
        price=price,
        price_text=price_text,
        available=status in (None, "AVAILABLE"),
    )


def find_pickup_slot(html: str, store_id: str, slot_id: str) -> tuple[Timeslot, str | None] | None:
    """(slot, slot-store-id) for one pickup slot radio of a store in service-timeslot, or None."""
    container = LexborHTMLParser(html).css_first(f'.timeslotPickupContainer[data-store-id="{store_id}"]')
    if container is None:
        return None
    for radio in container.css(f'input[type=radio][name="select-timeslot-{PICKUP}"]'):
        if radio.attributes.get("slot-id") == slot_id:
            return _slot(radio), radio.attributes.get("slot-store-id")
    return None


def parse_pickup_days(html: str, store_id: str) -> list[Day]:
    """Days (with status) and pickup slots of one store from service-timeslot."""
    tree = LexborHTMLParser(html)
    days: dict[str, Day] = {}
    for btn in tree.css(".day-selection_btn"):
        m = _DATE_CLASS.search(btn.attributes.get("class") or "")
        if not m or _ancestor_store(btn) not in (store_id, None):
            continue
        date = btn.attributes.get("data-timeslot-date") or m.group(1)
        status = btn.attributes.get("data-timeslot-status")
        if date in days and days[date].status and not status:
            continue
        days[date] = Day(date=date, label=clean_text(btn.text(separator=" ")), status=status)

    container = tree.css_first(f'.timeslotPickupContainer[data-store-id="{store_id}"]')
    if container is not None:
        for radio in container.css(f'input[type=radio][name="select-timeslot-{PICKUP}"]'):
            slot = _slot(radio)
            date = slot.start[:10]
            days.setdefault(date, Day(date=date, status="AVAILABLE")).slots.append(slot)
    return [days[d] for d in sorted(days)]


_CART_WITHOUT_SLOT = re.compile(r"var cartWithoutTimeslot = (true|false);")
_SERVICE_TYPE_VAR = re.compile(r'var serviceType = "(\w*)";')


def _header_timeslot(tree: LexborHTMLParser) -> str | None:
    """Booked slot from the header, e.g. 'Demain à 13h-14h'. None when no slot is booked."""
    hour = tree.css_first(".openStoreLocatorTimeslotValue.timeslotHour")
    hour_text = clean_text(hour.text()) if hour else None
    if not hour_text:
        return None
    day = tree.css_first(".openStoreLocatorTimeslotValue.timeslotDescription")
    return clean_text(" ".join(filter(None, [clean_text(day.text()) if day else None, hour_text])))


def _header_pickup_context(tree: LexborHTMLParser, html: str) -> ServiceContext | None:
    """Pickup context from `var serviceType` and the page header, when there is no current-store input.

    Jean Coutu never has that input; grocery banners drop it once a timeslot is booked (verified on
    Super C 2026-11-09). The header shows the store name (no id or address) and the booked slot.
    """
    m = _SERVICE_TYPE_VAR.search(html)
    if not m or m.group(1) != "pickup":
        return None
    node = tree.css_first(".p-location.locationPickup .store-name")
    name = clean_text(node.text()) if node else None
    if not name or name == "null":
        return None
    slot = _header_timeslot(tree)
    without = _CART_WITHOUT_SLOT.search(html)
    selected = True if slot else (False if without and without.group(1) == "true" else None)
    return ServiceContext(service_type="PICK_UP_IN_STORE", store_name=name, timeslot_selected=selected,
                          timeslot=slot)


def parse_service_context(html: str) -> ServiceContext | None:
    """Current service context from a full page (e.g. /mon-panier)."""
    tree = LexborHTMLParser(html)
    node = tree.css_first(".store-to-assign.current-store input[data-store-id]")
    if node is None:
        return _header_pickup_context(tree, html)
    a = node.attributes
    m = _CART_WITHOUT_SLOT.search(html)
    return ServiceContext(
        service_type=a.get("data-hybris-service-type"),
        store_id=a.get("data-store-id"),
        store_name=clean_text(a.get("data-store-name")),
        store_address=clean_text(a.get("data-store-address")),
        timeslot_selected=(m.group(1) == "false") if m else None,
        timeslot=_header_timeslot(tree),
    )
