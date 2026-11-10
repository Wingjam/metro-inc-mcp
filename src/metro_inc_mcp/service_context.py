"""Stores, pickup timeslots and the cart's pickup store."""

from __future__ import annotations

import json
import logging
import re
import time

from .auth import AuthManager
from .client import GroceryClient
from .config import Language
from .errors import CaptchaRequired, GroceryError, StoreNotFound, UpstreamError
from .models import SetStoreResult, StoreList, TimeslotList
from .parsing.service import (
    parse_form_state,
    parse_pickup_days,
    parse_pickup_point,
    parse_store_list,
)

log = logging.getLogger(__name__)

_POSTAL = re.compile(r"^\s*([A-Za-z]\d[A-Za-z])\s*-?\s*(\d[A-Za-z]\d)\s*$")
_STORE_ID = re.compile(r"^\d{1,8}$")


class InvalidInput(GroceryError):
    pass


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
