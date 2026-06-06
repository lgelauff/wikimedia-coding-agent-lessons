# Wikimedia lessons

## Docs to fetch at project start

- 🤖 https://www.mediawiki.org/wiki/Extension:OAuth/For_developers
- 🤖 https://www.mediawiki.org/wiki/OAuth/For_Developers/OAuth_2.0
- 🤖 https://www.mediawiki.org/wiki/API:Main_page
- 🤖 https://www.mediawiki.org/wiki/API:Userinfo
- 🤖 https://www.mediawiki.org/wiki/API:User_group_membership
- 🤖 https://commons.wikimedia.org/wiki/Commons:API/Images

🤖 = fetchable via WebFetch at conversation start.

---

## OAuth 2.0

- **Public consumers require admin approval** — plan for several days of wait time. Owner-only consumers are active immediately.
- **Confidential client**: yes, for server-side apps.
- **Allowed grants**: Authorization code only. Leave Refresh token and Client credentials unchecked.
- **Callback URL** must exactly match what the app uses — including protocol and path.
- For identity-only use, select "User identity verification only" as the grant scope.
- **OAuth 2.0 scope for identity is `basic`**, not `openid`. Use `'scope': 'basic'` in the authorization request. Requesting `openid` returns `invalid_scope` even when "User identity verification only" is selected — `openid` is not a supported scope on Wikimedia's OAuth 2.0 implementation.

## MediaWiki API — overview

Wikimedia runs a well-documented, stable HTTP API on every wiki. It is the **official and preferred way** to access wiki data programmatically — always use it instead of scraping HTML. Scraping is fragile (page layout changes break it), violates `robots.txt` on some paths, and puts unnecessary load on the servers. The API is explicitly designed for programmatic access, versioned, and maintained.

The API is available at `https://<wiki>/w/api.php` (e.g. `https://en.wikipedia.org/w/api.php`). It supports both GET and POST, returns JSON by default, and is self-documenting — visit the URL in a browser for an interactive explorer.

Full reference: https://www.mediawiki.org/wiki/API:Main_page

Most calls follow the pattern:
```
GET /w/api.php?action=<action>&format=json&<params>
```

Common actions: `query` (fetch data), `parse` (render wikitext), `edit` (write, requires auth).

## MediaWiki API — specifics

- Use `action=query&meta=userinfo&uiprop=groups|rights|options` to get user rights, groups, and preferences in one call.
- `uiprop=options` returns all user preferences including skin and gender — useful for personalisation without extra calls.
- Add `maxlag=5` to bulk requests to be a good citizen on shared infrastructure.

## Commons thumbnail API

- Use `action=query&prop=imageinfo&iiprop=url&iiurlwidth=N` to get a resized thumbnail URL.
- Always returns PNG regardless of source format — eliminates the need for SVG rendering libraries like cairosvg.
- Much simpler than trying to fetch and convert the original file.

## requests.Session — connection reuse for repeated API calls

When making multiple calls to the same Wikimedia host (e.g. many Wikipedia articles in a loop), use `requests.Session` instead of `requests.get`. A Session reuses the underlying TCP connection (HTTP keep-alive), eliminating the TLS handshake and connection overhead on every call. On Wikipedia's API this is measurable — dozens of calls per second vs. one-handshake-per-request.

Pattern: maintain one Session per host, keyed by `scheme://netloc`:

```python
import requests
from urllib.parse import urlparse

_sessions: dict[str, requests.Session] = {}

def _session_for(url: str) -> requests.Session:
    key = "{0.scheme}://{0.netloc}".format(urlparse(url))
    if key not in _sessions:
        s = requests.Session()
        s.headers.update({"User-Agent": MY_UA})
        _sessions[key] = s
    return _sessions[key]
```

Then call `_session_for(url).get(api_url, params=params, timeout=20)` instead of `requests.get(...)`. The rate-limit `wait()` call goes before the request as usual — Session reuse does not affect rate limiting, it only reduces connection overhead.

- Set default headers on the Session (`s.headers.update(...)`) so they apply to every call automatically.
- One Session per host is the right granularity — don't share a session across different domains.
- Sessions are not thread-safe; if parallelising, give each thread its own Session.
- Reference: https://requests.readthedocs.io/en/latest/user/advanced/#session-objects
