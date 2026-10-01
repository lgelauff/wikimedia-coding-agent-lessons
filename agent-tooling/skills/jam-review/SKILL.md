---
name: jam-review
description: >-
  Review a Jam recording (a jam.dev link: a recorded browser tab with its console, network
  requests, user actions and video) and turn it into an evidence-based finding: what happened,
  where it went wrong, how to reproduce it, and what to look at next. Use whenever someone
  shares a `jam.dev/c/...` link or says "look at this jam", "check this recording", "why did this
  break, here's the jam" — even without saying "review". Use it INSTEAD of watching the video and
  describing it: the video is the obvious move and the weakest evidence, because what went wrong
  is in the console and the network log, and a recording watched first sends you after what the
  person thought rather than what the tab did. This reads the data first (console errors, failed
  and suspicious requests, the action timeline) and uses the video only to confirm. Handles Jams
  outside the connected workspace by falling back to the public share page.
---

# jam-review — review a Jam recording

Claude Code adapter over the agent-neutral **jam-review playbook**. The method lives in the playbook;
this file is the Claude-specific wiring.

Read the playbook: `${AGENT_TOOLING_ROOT}/playbooks/jam-review.md`. Follow its steps 0–7 in order,
and its privacy rules.

## Access in Claude Code

1. **Jam connector (MCP)**, when connected. Call `getDetails` first (Jam ID or full link). Then, in
   the playbook's order:
   - console: `getConsoleLogs` with `logLevel: ["error"]`, then `["warn"]`;
   - network: `getNetworkRequests` with `statusCode: ["4xx","5xx"]` (bodies of failures come by
     default); then the app's own host with `bodies: "all"` around the failure;
   - actions: `getUserEvents`; extras: `getMetadata`;
   - last: `getVideoTranscript`, `analyzeVideo` (or `getScreenshots` for a screenshot Jam).
   Use the `intent` field to say why each call is made.
2. **`JamNotFound`** means the Jam is in another workspace (the connector sees only its own; a
   public link does not change that). If the link is publicly viewable, open it in the built-in
   browser (`mcp__Claude_Browser__*`): the share page's DevTools panel has Info, Console, Network,
   Actions and Backend tabs.
   - Read text with `get_page_text` / `find`; use the panel's "Errors only" box and type filters
     (Fetch/XHR) instead of scrolling the whole table; click a row for its details and response.
   - The "MCP" button on the page is only a setup prompt; it gives no access.
   - `jam.dev` is in the Mandated Services Registry for this purpose only: the one shared link, no
     crawling, no other pages.
3. Neither works → say which and why, and ask for the Jam to be shared into the connected
   workspace, the connector to be signed in to the right one, or the link to be made viewable.

## Output

The finding block from the playbook's step 7, in chat. Then offer, don't do: reproduce it live
(browser-verify), draft an issue (shown first, never posted without a yes), or write the failing
test. Keep personal details out of everything you write, as the playbook says.
