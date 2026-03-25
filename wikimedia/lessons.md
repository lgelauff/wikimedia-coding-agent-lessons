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

## MediaWiki API

- Use `action=query&meta=userinfo&uiprop=groups|rights|options` to get user rights, groups, and preferences in one call.
- `uiprop=options` returns all user preferences including skin and gender — useful for personalisation without extra calls.
- Add `maxlag=5` to bulk requests to be a good citizen on shared infrastructure.

## Commons thumbnail API

- Use `action=query&prop=imageinfo&iiprop=url&iiurlwidth=N` to get a resized thumbnail URL.
- Always returns PNG regardless of source format — eliminates the need for SVG rendering libraries like cairosvg.
- Much simpler than trying to fetch and convert the original file.
