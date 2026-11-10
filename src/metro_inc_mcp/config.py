"""Runtime configuration from environment variables.

Metro inc. runs Super C, Metro and Food Basics on the same e-commerce platform. Only the domain,
the search paths and the available languages differ, so one server handles all three banners.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Language = Literal["fr", "en"]
LANGUAGES: tuple[Language, ...] = ("fr", "en")


@dataclass(frozen=True)
class SitePaths:
    """Paths for one language of one banner."""

    search: str
    search_page: str  # format with page=N
    autocomplete: str
    cart: str
    service: str  # prefix of the service-and-timeslot endpoints


@dataclass(frozen=True)
class BannerConfig:
    key: str
    name: str
    base_url: str
    paths: dict[str, SitePaths] = field(default_factory=dict)
    login_path: str = "/b2c-login"
    kind: str = "grocery"  # 'grocery' or 'pharmacy'
    pickup_timeslots: bool = True  # False: pickup has no timeslot to choose (Jean Coutu)
    # POST that assigns a pickup store without a slot. None: '<service prefix>/store' in the primary language.
    assign_store_path: str | None = None

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(self.paths)

    @property
    def primary_language(self) -> Language:
        """Language used for write calls (the one verified live)."""
        return next(iter(self.paths))  # type: ignore[return-value]

    def resolve_language(self, language: str | None) -> Language:
        """The requested language if the banner has it, otherwise its primary language."""
        return language if language in self.paths else self.primary_language  # type: ignore[return-value]


def _french_english(search_fr: str, search_en: str) -> dict[str, SitePaths]:
    return {
        "fr": SitePaths(search=search_fr, search_page=f"{search_fr}-page-{{page}}",
                        autocomplete="/autocompleteSearchProducts", cart="/mon-panier",
                        service="/service-and-timeslot"),
        "en": SitePaths(search=search_en, search_page=f"{search_en}-page-{{page}}",
                        autocomplete="/en/autocompleteSearchProducts", cart="/en/my-cart",
                        service="/en/service-and-timeslot"),
    }


BANNERS = {
    "superc": BannerConfig(
        key="superc", name="Super C", base_url="https://www.superc.ca",
        paths=_french_english("/recherche", "/en/search"),
    ),
    "metro": BannerConfig(
        key="metro", name="Metro", base_url="https://www.metro.ca",
        paths=_french_english("/epicerie-en-ligne/recherche", "/en/online-grocery/search"),
    ),
    "foodbasics": BannerConfig(
        key="foodbasics", name="Food Basics", base_url="https://www.foodbasics.ca",
        paths={"en": SitePaths(search="/search", search_page="/search-page-{page}",
                               autocomplete="/autocompleteSearchProducts", cart="/my-cart",
                               service="/service-and-timeslot")},
    ),
    "jeancoutu": BannerConfig(
        key="jeancoutu", name="Jean Coutu", base_url="https://www.jeancoutu.com",
        paths={
            "fr": SitePaths(search="/magasiner/recherche", search_page="/magasiner/recherche-page-{page}",
                            autocomplete="/magasiner/autocompleteSearchProducts", cart="/magasiner/mon-panier",
                            service="/magasiner/service-and-timeslot"),
            "en": SitePaths(search="/en/shop/search", search_page="/en/shop/search-page-{page}",
                            autocomplete="/en/shop/autocompleteSearchProducts", cart="/en/shop/my-cart",
                            service="/en/shop/service-and-timeslot"),
        },
        login_path="/magasiner/b2c-login",
        kind="pharmacy",
        pickup_timeslots=False,
        # '/magasiner/service-and-timeslot/store' is 404; the site's panel posts here (assignStoreAndTimeslotToCartUrl).
        assign_store_path="/fr/magasiner/service-and-timeslot/store-timeslot",
    ),
}


# Shared by every banner (the Moi ID login is the same) and outside the repo.
DEFAULT_COOKIES_FILE = Path("~/.metro-inc-mcp/moiid-cookies.json")


def cookies_file_from_env() -> Path:
    """METRO_COOKIES_FILE, or DEFAULT_COOKIES_FILE when it is unset or empty."""
    return Path(os.environ.get("METRO_COOKIES_FILE") or DEFAULT_COOKIES_FILE).expanduser()


@dataclass(frozen=True)
class Settings:
    banner: BannerConfig
    language: Language
    cookies_file: Path | None
    min_interval: float
    impersonate: str
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        # Required: picking the wrong banner by default would act on the wrong cart.
        raw = os.environ.get("METRO_BANNER", "")
        banner_key = raw.lower().replace(" ", "").replace("-", "").replace("_", "")
        if banner_key not in BANNERS:
            raise ValueError(f"METRO_BANNER must be one of: {', '.join(BANNERS)} (got {raw!r})")
        banner = BANNERS[banner_key]
        language = os.environ.get("METRO_LANGUAGE", banner.primary_language).lower()
        if language not in LANGUAGES:
            raise ValueError(f"METRO_LANGUAGE={language!r} is not supported (use 'fr' or 'en')")
        return cls(
            banner=banner,
            language=banner.resolve_language(language),
            cookies_file=cookies_file_from_env(),
            min_interval=float(os.environ.get("METRO_MIN_INTERVAL", "2.0")),
            impersonate=os.environ.get("METRO_IMPERSONATE", "chrome"),
            log_level=os.environ.get("METRO_LOG_LEVEL", "WARNING").upper(),
        )

    def resolve_language(self, language: str | None) -> Language:
        return self.banner.resolve_language(language or self.language)

    def paths(self, language: str | None = None) -> SitePaths:
        return self.banner.paths[self.resolve_language(language)]

    @property
    def write_paths(self) -> SitePaths:
        return self.banner.paths[self.banner.primary_language]
