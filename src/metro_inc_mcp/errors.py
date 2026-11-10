"""Errors with messages written for the assistant (they are returned as tool errors).

`site` is the banner's website (e.g. 'superc.ca', 'metro.ca').
"""


class GroceryError(Exception):
    """Base class. The message is shown to the assistant."""


class RateLimited(GroceryError):
    def __init__(self, site: str) -> None:
        super().__init__(f"{site} is rate limiting requests (HTTP 429). Wait a minute before searching again.")


class CloudflareBlocked(GroceryError):
    def __init__(self, site: str) -> None:
        super().__init__(
            f"{site} returned a Cloudflare challenge. The browser impersonation no longer passes; "
            "try another METRO_IMPERSONATE value (e.g. 'safari') or update curl_cffi."
        )


class SiteMaintenance(GroceryError):
    def __init__(self, site: str) -> None:
        super().__init__(
            f"{site} is down for maintenance (every page redirects to its maintenance page). Nothing was changed. "
            "This is not a login problem: try again later."
        )


class SiteChanged(GroceryError):
    def __init__(self, what: str) -> None:
        super().__init__(f"Could not parse the page ({what}). The site layout may have changed.")


class NotConfigured(GroceryError):
    def __init__(self, detail: str = "No Moi ID cookie file.") -> None:
        super().__init__(
            f"{detail} Cart and store tools need a logged-in session: ask the user to run `metro-inc-mcp login` "
            "(it opens a browser to log in and saves the cookies), or to export the Moi ID (auth.moiid.ca) "
            "cookies to a JSON file and set METRO_COOKIES_FILE to its path."
        )


class AuthExpired(GroceryError):
    def __init__(self, detail: str = "The Moi ID session has expired.") -> None:
        super().__init__(
            f"{detail} Ask the user to run `metro-inc-mcp login` (it opens a browser to log in and saves "
            "the cookies), or to log in on the website and re-export the Moi ID (auth.moiid.ca) cookies to "
            "the cookie file (METRO_COOKIES_FILE, default ~/.metro-inc-mcp/moiid-cookies.json)."
        )


class NoServiceContext(GroceryError):
    def __init__(self) -> None:
        super().__init__(
            "The cart has no store or delivery address yet (HTTP 409). Choose a pickup store first "
            "(find_stores, then set_pickup_store), or set it on the website."
        )


class StoreNotFound(GroceryError):
    def __init__(self, store_id: str, postal_code: str) -> None:
        super().__init__(f"Store {store_id} does not offer pickup near {postal_code}. Use find_stores for that postal code.")


class CaptchaRequired(GroceryError):
    def __init__(self, site: str) -> None:
        super().__init__(f"{site} now requires a reCAPTCHA to change the store. Ask the user to choose the store on {site}.")


class UpstreamError(GroceryError):
    def __init__(self, status: int, path: str) -> None:
        super().__init__(f"The website returned HTTP {status} for {path}.")
