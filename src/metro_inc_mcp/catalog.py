"""Product search (anonymous or logged in; results follow the cart's store when logged in)."""

from __future__ import annotations

from .client import GroceryClient
from .config import Language
from .models import QuickSearchResult, SearchResult
from .parsing.products import parse_autocomplete, parse_search_page


async def search_products(client: GroceryClient, query: str, page: int = 1,
                          language: Language | None = None) -> SearchResult:
    lang = client.settings.resolve_language(language)
    paths = client.settings.paths(lang)
    path = paths.search if page <= 1 else paths.search_page.format(page=page)
    html = await client.get_text(path, params={"filter": query}, cache=True)
    total, products = parse_search_page(html, client.base_url)
    return SearchResult(query=query, language=lang, page=max(page, 1), total=total, products=products)


async def quick_search(client: GroceryClient, query: str, language: Language | None = None) -> QuickSearchResult:
    lang = client.settings.resolve_language(language)
    html = await client.post_text(
        client.settings.paths(lang).autocomplete,
        params={"freeText": query, "tabletMobile": "false", "previousSuggestion": ""},
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        cache=True,
    )
    total, suggestions, products = parse_autocomplete(html, client.base_url)
    return QuickSearchResult(query=query, language=lang, total=total, suggestions=suggestions, products=products)
