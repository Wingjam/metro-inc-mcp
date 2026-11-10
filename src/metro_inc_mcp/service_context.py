"""Stores, pickup timeslots and the cart's pickup store."""

from __future__ import annotations

import json
import logging
import re
import time

from .auth import AuthManager, page_is_authenticated
from .client import GroceryClient
from .config import Language
from .errors import (
    AuthExpired,
    CaptchaRequired,
    GroceryError,
    StoreNotFound,
    UpstreamError,
)
from .models import (
    BookTimeslotResult,
    ServiceContext,
    SetStoreResult,
    StoreList,
    TimeslotList,
)
from .parsing.service import (
    find_pickup_slot,
    parse_form_state,
    parse_pickup_days,
    parse_pickup_point,
    parse_service_context,
    parse_store_list,
)

log = logging.getLogger(__name__)

_POSTAL = re.compile(r"^\s*([A-Za-z]\d[A-Za-z])\s*-?\s*(\d[A-Za-z]\d)\s*$")
_STORE_ID = re.compile(r"^\d{1,8}$")


class InvalidInput(GroceryError):
    pass


class SlotNotAvailable(GroceryError):
    def __init__(self, slot_id: str, store_id: str) -> None:
        super().__init__(f"Timeslot {slot_id} is not offered or no longer available at store {store_id}. "
                         "Call get_timeslots again and pick another slot.")


def normalize_postal_code(value: str) -> str:
    """'h2x1y4' -> 'H2X 1Y4'."""
    m = _POSTAL.match(value or "")
    if not m:
        raise InvalidInput(f"{value!r} is not a Canadian postal code (e.g. 'H2X 1Y4').")
    return f"{m.group(1)} {m.group(2)}".upper()


def _check_store_id(value: str) -> str:
    value = (value or "").strip()
    if not _STORE_ID.match(value):
        raise InvalidInput(f"{value!r} is not a store id (digits, e.g. '274'). Use find_stores to get one.")
    return value


class ServiceContextService:
    def __init__(self, client: GroceryClient, auth: AuthManager) -> None:
        self.client = client
        self.auth = auth

    def _prefix(self, language: Language | None = None) -> str:
        return self.client.settings.paths(language).service

    async def find_stores(self, postal_code: str, language: Language | None = None) -> StoreList:
        postal = normalize_postal_code(postal_code)
        if not self.client.settings.banner.pickup_timeslots:
            # Jean Coutu has no service-choice page; the service-timeslot panel lists the pickup stores.
            html = await self.client.get_text(f"{self._prefix(language)}/service-timeslot", ajax=True, cache=True,
                                              params={"deliveryPostalCode": postal, "fromSubmit": "false"})
            return StoreList(postal_code=postal, stores=parse_store_list(html, pickup_only=True))
        html = await self.client.get_text(f"{self._prefix(language)}/service-choice", ajax=True, cache=True,
                                          params={"choiceTypeService": "EMPTY_SERVICE", "deliveryPostalCode": postal})
        return StoreList(postal_code=postal, stores=parse_store_list(html))

    async def _timeslot_page(self, store_id: str, postal: str, language: Language | None) -> str:
        return await self.client.get_text(f"{self._prefix(language)}/service-timeslot", ajax=True, params={
            "deliveryPostalCode": postal, "updateTypeServiceFromPanel": "PICKUP", "pickupStoreId": store_id,
            "fromSubmit": "false", "_": str(int(time.time() * 1000)),
        })

    async def get_timeslots(self, store_id: str, postal_code: str, language: Language | None = None) -> TimeslotList:
        store_id = _check_store_id(store_id)
        postal = normalize_postal_code(postal_code)
        lang = self.client.settings.resolve_language(language)
        html = await self._timeslot_page(store_id, postal, lang)
        point, name = parse_pickup_point(html, store_id)
        if point is None:
            raise StoreNotFound(store_id, postal)
        if not self.client.settings.banner.pickup_timeslots:
            return TimeslotList(store_id=store_id, store_name=name, service_point_id=point, language=lang, days=[],
                                note=f"{self.client.settings.banner.name} pickup has no timeslot to choose: "
                                     "the order is picked up at the store when ready.")
        return TimeslotList(store_id=store_id, store_name=name, service_point_id=point, language=lang,
                            days=parse_pickup_days(html, store_id))

    async def set_pickup_store(self, store_id: str, postal_code: str) -> SetStoreResult:
        """Assign a pickup store to the user's cart, without booking a timeslot ('Choisir plus tard')."""
        store_id = _check_store_id(store_id)
        postal = normalize_postal_code(postal_code)
        await self.auth.ensure_logged_in()
        write_lang = self.client.settings.banner.primary_language
        html = await self._timeslot_page(store_id, postal, write_lang)
        point, name = parse_pickup_point(html, store_id)
        if point is None:
            raise StoreNotFound(store_id, postal)
        payload = {
            "serviceType": "PICK_UP_IN_STORE",
            "storeId": store_id,
            "deliveryPostalCode": postal.replace(" ", ""),
            "servicePointId": point,
            "formStateId": parse_form_state(html),
        }
        path = self.client.settings.banner.assign_store_path or f"{self._prefix(write_lang)}/store"
        resp = await self.client.request("POST", path, ajax=True,
                                         headers={"Content-Type": "application/json", "Accept": "text/html, */*; q=0.01"},
                                         data=json.dumps(payload))
        h = {k.lower(): v for k, v in resp.headers.items()}
        if h.get("recaptchafailed") == "true":
            raise CaptchaRequired(self.client.site)
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, path)
        log.info("pickup store set to %s (%s)", store_id, h.get("updateheaderstore"))
        return SetStoreResult(
            store_id=store_id,
            store_name=h.get("updateheaderstore") or name,
            service_type="PICK_UP_IN_STORE" if h.get("cartservicetype") == "pickup" else h.get("cartservicetype"),
            store_changed=(h["cartstorehaschanged"] == "true") if "cartstorehaschanged" in h else None,
            timeslot=h.get("updateheadertimeslot"),
        )

    async def _current_context(self) -> ServiceContext | None:
        """Service context of the account cart (pickup store, timeslot flag), with one re-login if needed."""
        await self.auth.ensure_logged_in()
        cart_path = self.client.settings.write_paths.cart
        html = await self.client.get_text(cart_path)
        if page_is_authenticated(html) is False:
            self.auth.mark_logged_out()
            await self.auth.ensure_logged_in()
            html = await self.client.get_text(cart_path)
            if page_is_authenticated(html) is False:
                raise AuthExpired()
        return parse_service_context(html)

    async def book_timeslot(self, store_id: str, postal_code: str, slot_id: str,
                            confirm: bool = False) -> BookTimeslotResult:
        """Book a pickup timeslot for the cart (POST store-timeslot). Without confirm, only a preview."""
        banner = self.client.settings.banner
        if not banner.pickup_timeslots:
            raise InvalidInput(f"{banner.name} pickup has no timeslot to book: the order is picked up when ready.")
        store_id = _check_store_id(store_id)
        postal = normalize_postal_code(postal_code)
        slot_id = (slot_id or "").strip()
        if not slot_id.isdigit():
            raise InvalidInput(f"{slot_id!r} is not a slot id (digits). Use get_timeslots to get one.")
        current = await self._current_context()
        write_lang = banner.primary_language
        html = await self._timeslot_page(store_id, postal, write_lang)
        point, name = parse_pickup_point(html, store_id)
        if point is None:
            raise StoreNotFound(store_id, postal)
        found = find_pickup_slot(html, store_id, slot_id)
        if found is None or not found[0].available:
            raise SlotNotAvailable(slot_id, store_id)
        slot, slot_store_id = found
        current_id = current.store_id if current else None
        if current_id:
            changes_store = current_id != store_id
        elif current and current.store_name and name:  # a booked cart page shows only the store name
            changes_store = current.store_name != name
        else:
            changes_store = None
        result = BookTimeslotResult(
            booked=False, store_id=store_id, store_name=name, slot=slot, current_store_id=current_id,
            current_timeslot=current.timeslot if current else None, changes_store=changes_store,
        )
        if not confirm:
            result.note = ("Preview only, nothing was booked. Show this to the user and call again with "
                           "confirm=true once they agree. Once booked, the site holds the slot for 2 hours.")
            return result

        payload = {
            "serviceType": "PICK_UP_IN_STORE",
            "storeId": store_id,
            "deliveryPostalCode": postal.replace(" ", ""),
            "servicePointId": point,
            "formStateId": parse_form_state(html),
            "slot": slot_id,
            "slotStoreId": slot_store_id or point,
            "slotFrom": slot.start,
            "slotTo": slot.end,
            "inCheckoutPage": False,
        }
        path = f"{self._prefix(write_lang)}/store-timeslot"
        resp = await self.client.request("POST", path, ajax=True,
                                         headers={"Content-Type": "application/json", "Accept": "text/html, */*; q=0.01"},
                                         data=json.dumps(payload))
        h = {k.lower(): v for k, v in resp.headers.items()}
        if h.get("recaptchafailed") == "true":
            raise CaptchaRequired(self.client.site)
        if h.get("timesloterror") == "true":
            raise SlotNotAvailable(slot_id, store_id)
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, path)
        log.info("timeslot %s booked at store %s", slot_id, store_id)
        result.booked = True
        result.store_name = h.get("updateheaderstore") or name
        result.timeslot = h.get("updateheadertimeslot")
        after = await self._current_context()
        if after is None or after.timeslot_selected is not True:
            result.note = "The site answered 200 but the cart does not show a timeslot yet: check view_cart."
        else:
            # Cart page text once a slot is booked: "Votre plage horaire est réservée pour les 2 prochaines heures."
            result.note = ("The site holds this slot for 2 hours: the user should place the order on "
                           f"{self.client.site} before then.")
        return result
