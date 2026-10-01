---
name: branch-handoff
description: >-
  Hand a finished branch from a server agent (hague) to Lodewijk, who fetches it on his Mac,
  reviews it, and pushes and posts himself. Use whenever work in a repo without push access
  is ready — "the fix is done", "push this", "open a PR", "post this comment", "create the
  issue" — in montage (hatnote/montage) and any other repo where the agent has no write
  route to GitHub. Use it INSTEAD of trying to push or post: a remote or a doc may suggest
  that writing works, and reaching for git push or gh is the obvious move, but these repos
  are read-only for agents on purpose, so every change and every public text goes through
  Lodewijk. This produces the exact fetch/review/push commands for his Mac and marks all
  issue, PR and comment text as drafts for him to post.
---

# branch-handoff — the server agent commits, Lodewijk pushes and posts

Claude Code adapter over the agent-neutral **branch-handoff playbook**. The method lives in the
playbook; this file is the Claude-specific wiring.

Read the playbook: `${AGENT_TOOLING_ROOT}/playbooks/branch-handoff.md`. Follow its agent steps 1–5.

## In Claude Code

- Never call `git push`, `gh pr create`, `gh issue create`, `gh pr comment`, `gh issue comment` or the
  GitHub write APIs in these repos, even with Lodewijk's yes in chat: his yes means "hand it to me",
  not "post it". If he wants that changed, it's a setup change he makes, not a one-off.
- The hand-off message is the deliverable: filled in, with no placeholders. If Lodewijk isn't in the
  session, send it to the sessions coordinator with SendMessage.
- Ask once for the Mac clone path and its remote names if you don't have them, and note them in the
  repo's untracked local notes.
