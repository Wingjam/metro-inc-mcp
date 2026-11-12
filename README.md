# metro-inc-mcp

Unofficial [MCP](https://modelcontextprotocol.io) server for the online stores of [Metro inc.](https://corpo.metro.ca) banners: the grocery sites [Super C](https://www.superc.ca), [Metro](https://www.metro.ca) and [Food Basics](https://www.foodbasics.ca), and the pharmacy [Jean Coutu](https://www.jeancoutu.com). It lets an AI assistant search products, manage your cart and choose a pickup store, in French or English.

> **Unofficial.** Not affiliated with, endorsed by or supported by METRO inc. or any of its banners. It uses the websites' undocumented endpoints, which can change at any time. Personal use only; keep request volume low. Checkout and payment are not supported: you finish the order on the website.

## Banners

The sites run on the same platform. One server instance handles one banner (and its cart), chosen with `METRO_BANNER`.

| `METRO_BANNER` | Site | Kind | Languages | Pickup timeslots |
|---|---|---|---|---|
| `superc` | superc.ca | grocery | fr, en | yes |
| `metro` | metro.ca | grocery | fr, en | yes |
| `foodbasics` | foodbasics.ca | grocery | en | yes |
| `jeancoutu` | jeancoutu.com | pharmacy (over-the-counter products, no prescriptions) | fr, en | no (pickup when ready) |

The same Moi ID login works for all of them; each banner has its own cart. Brunet has no online cart, so it is not supported.

## Tools

| Tool | What it does | Login |
|---|---|---|
| `quick_search` | top 3 products for a query, with prices and suggestions | no |
| `search_products` | full search, about 42 products per page | no |
| `view_cart` | cart lines, estimated total, pickup store | yes |
| `add_to_cart` | add one or more products | yes |
| `update_cart_quantity` | set the quantity of a product in the cart | yes |
| `remove_from_cart` | remove a product | yes |
| `clear_cart` | empty the cart in one call; returns what was removed so it can be added back | yes |
| `view_favorites` | the account's saved favorites ("Mes favoris"), with prices and saved quantities | yes |
| `add_to_favorites` | save one or more products to the favorites | yes |
| `remove_from_favorites` | remove a product from the favorites | yes |
| `find_stores` | pickup stores near a postal code | no |
| `get_timeslots` | pickup days and timeslots of a store (read only) | no |
| `set_pickup_store` | choose the cart's pickup store; also removes a booked timeslot | yes |
| `book_timeslot` | book a pickup timeslot: preview by default, books only with `confirm=true`. The site holds the slot for 2 hours, so book it just before placing the order (not on Jean Coutu) | yes |

Read tools take an optional `language` (`fr` or `en`). French and English use separate search indexes, so search in the user's language. On English-only banners the argument is ignored.

The sites keep several copies of the favorites list that are not always in sync: after a change, some reads still show the old list (seen for more than a day on removed favorites). The list on the website itself was correct.

Not supported yet: home delivery, coupons, purchase history.

## Run

Requires [uv](https://docs.astral.sh/uv/).

### Without cloning

`uvx` downloads the server from GitHub and runs it:

```sh
METRO_BANNER=superc uvx --from git+https://github.com/Wingjam/metro-inc-mcp metro-inc-mcp   # stdio
uvx --from "metro-inc-mcp[login] @ git+https://github.com/Wingjam/metro-inc-mcp" metro-inc-mcp login
```

Example MCP client config (Kiro `.kiro/settings/mcp.json`, Claude Desktop, ...), one entry per banner:

```json
{
  "mcpServers": {
    "superc": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Wingjam/metro-inc-mcp", "metro-inc-mcp"],
      "env": { "METRO_BANNER": "superc" }
    },
    "metro": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Wingjam/metro-inc-mcp", "metro-inc-mcp"],
      "env": { "METRO_BANNER": "metro" }
    }
  }
}
```

`uvx` caches the build: run `uvx --refresh --from git+https://github.com/Wingjam/metro-inc-mcp metro-inc-mcp login --help` to get the latest version, or pin one with `git+https://github.com/Wingjam/metro-inc-mcp@<commit or tag>`.

### From a clone

```sh
uv sync
METRO_BANNER=superc uv run metro-inc-mcp # stdio
uv run pytest # offline parser tests (saved pages, no network)
uv run ruff check # lint (settings in pyproject.toml)
```

Example MCP client config for a clone, one entry per banner:

```json
{
  "mcpServers": {
    "superc": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/metro-inc-mcp", "metro-inc-mcp"],
      "env": { "METRO_BANNER": "superc" }
    },
    "metro": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/metro-inc-mcp", "metro-inc-mcp"],
      "env": { "METRO_BANNER": "metro" }
    }
  }
}
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `METRO_BANNER` | required | `superc`, `metro`, `foodbasics` or `jeancoutu` |
| `METRO_COOKIES_FILE` | `~/.metro-inc-mcp/moiid-cookies.json` | JSON file with your Moi ID (`auth.moiid.ca`) cookies, needed for cart tools. Written by `metro-inc-mcp login` |
| `METRO_LANGUAGE` | banner's first language | default language of names, prices and labels: `fr` or `en` |
| `METRO_MIN_INTERVAL` | `2.0` | minimum seconds between requests |
| `METRO_IMPERSONATE` | `chrome` | `curl_cffi` browser impersonation target |
| `METRO_LOG_LEVEL` | `WARNING` | logs go to stderr |

## Logging in

The sites use Moi ID (Azure AD B2C) with a captcha, so the server never types your password. The Moi ID session ends after about 30 to 45 minutes without use, so expect to log in again when you come back to it.

The easy way needs Google Chrome:

```sh
uv sync --extra login
uv run metro-inc-mcp login # options: --banner metro, --cookies-file PATH, --timeout 600
```

It opens a Chrome window with a throwaway profile. You log in there (password and captcha); the command then saves the Moi ID cookies to `~/.metro-inc-mcp/moiid-cookies.json` (or `METRO_COOKIES_FILE`, mode 600), closes the window and checks that a silent login works. The browser is not automated while you log in, because the Cloudflare captcha rejects automated browsers. Set `METRO_CHROME` to use another Chromium-based browser.

By hand:

1. Log in on the website (any banner) in your browser.
2. Export the cookies of `auth.moiid.ca` to a JSON file (for example with the Cookie-Editor extension, "Export as JSON"). A Playwright `storageState` file also works.
3. Save it as `~/.metro-inc-mcp/moiid-cookies.json`, or set `METRO_COOKIES_FILE` to its path. Keep it private (`chmod 600`), never commit it.

The server uses these cookies to log in silently whenever its session expires, and writes refreshed cookies back to the file. When Moi ID asks for the password again, the tools return an error asking you to log in and export again. Several servers (one per banner) can share the same file.

## License

MIT
