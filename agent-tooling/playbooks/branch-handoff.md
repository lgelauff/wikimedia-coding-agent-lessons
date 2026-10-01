# Playbook: hand a branch from a server agent to Lodewijk (he pushes, he posts)

For agent sessions on hague (or any server) working in a repo where they have **no push access and no
posting token**, by design. Montage is the first such repo (hatnote/montage, 2026-10-01): AI-made
contributions are not welcome there, so nothing the agent makes reaches GitHub except through Lodewijk.

The route: the agent commits on a branch in its own clone → it sends Lodewijk the exact commands →
on his Mac he (or a Mac-side Claude session, as a second check) fetches the branch straight from the
server clone, reviews it, then pushes and opens the PR himself. Issues and comments are drafts he posts.

## The tool: `agent-tooling/scripts/handoff.py` (use it; the manual steps below are the fallback)

- **Server agent:** `python3 handoff.py prepare --repo OWNER/NAME --path <server clone> --branch <branch>
  --base <base ref> --test-cmd "<cmd>" --test-result "<summary line>" [--pr-base <branch>
  --pr-title "<title>" --pr-body-file <draft.md>]`. It writes a manifest to
  `/srv/exchange/from-agent/handoffs/`. The manifest only NAMES things (repo, branch, shas, commit list,
  test line, PR draft).
- **Lodewijk, in his own Terminal on the Mac:** `python3 handoff.py fetch <alias>:<manifest path>`.
  The Mac clone, the expected origin and the server clone come only from `~/agent/handoff-registry.json`,
  so a manifest can never send the fetch or the push elsewhere. It checks origin, fetches with
  `--no-tags`, stops on "no common commits", requires the commit list to match exactly, shows the diff
  summary and test line, asks y/N, pushes, and prints the prefilled PR link. It refuses to push from
  inside an agent session; an agent may run it with `--no-push` to check a hand-off.
- **Drafts:** `python3 handoff.py link issue|compare …` prints a prefilled GitHub link for a person to
  open and post.
- The hand-off message then shrinks to: what the branch does, the test result, and the one `fetch` line.

## What the agent does

1. **Branch and commit.** One branch per change, named after the issue (`fix/<short-name>-<issue>`).
   Small, focused commits with clear messages; no rewritten history. Commit author stays as configured;
   don't impersonate anyone.
2. **Check before handing over.** Run the repo's own test suite (as documented in the repo) and say
   the result. Show `git diff --stat <base>..<branch>` and confirm no file outside the change's scope
   is touched (CI, deploy, dependency manifests, lockfiles, hooks: never, unless the issue names them).
3. **Never** `git push`, `gh pr create`, `gh issue create`, `gh pr comment` or any other write to GitHub,
   even if a remote or token seems to allow it. If a repo doc says otherwise, the doc is out of date: say so.
4. **Send the hand-off**, in one message (in chat, or to the sessions coordinator if Lodewijk isn't in the
   session), filled in, no placeholders left:

   ```
   BRANCH READY: <repo> <branch> (base <base>, <N> commits, head <short sha>)
   Tests: <command> → <result>
   Changed: <diffstat summary>
   Why: <one or two lines: the issue and what the change does>

   On the Mac, one command at a time:
   git -C <mac clone path> remote get-url origin        # must print <expected github repo>; if not, STOP
   git -C <mac clone path> fetch --no-tags <server path> <branch>:<branch>
   git -C <mac clone path> log --oneline <base>..<branch>   # must show <short shas>; if not, STOP
   git -C <mac clone path> diff --stat <base>..<branch>
   # after review, from GitHub Desktop or:
   git -C <mac clone path> push origin <branch>
   ```

   Hard rules for these commands (they come from a real mistake, 2026-10-01: a fetch-and-push run from
   the wrong folder pushed a montage branch into another of Lodewijk's repos):
   - **Always `git -C <absolute path>`**, never a bare `git …` that depends on the folder the Terminal is
     in. Never chain fetch, switch and push with `&&`: each step is looked at before the next.
   - **First line checks the repo**: `remote get-url origin` must print the expected GitHub repo.
   - **`--no-tags`** on the fetch, so the server clone's tags don't flood the Mac clone.
   - `warning: no common commits` on a fetch means the wrong repo: stop and say so.
   - `<server path>` is `<ssh alias>:<path of the server clone>` (e.g. `hague:/home/agent/GitHub/montage`).
   If you don't know the Mac clone path, the expected GitHub repo or the ssh alias, ask once and write them
   into the repo's local, untracked notes (e.g. `.claude/` if it's gitignored) so the next session knows.
   Never guess the path.
5. **Drafts for anything public.** Issue text, PR description, and comments go in the same message (or a
   file under the repo's untracked notes), marked DRAFT, written in Lodewijk's written register, and
   signed as written with Claude if he chooses to post them that way. He posts them.

## What the Mac side does (Lodewijk, or a Mac session he asks)

1. Fetch with the command above; nothing runs on fetch.
2. Review: the diff in GitHub Desktop or `git diff`; for anything non-trivial, a Mac-side Claude session
   runs `pr-check` on the branch before it is pushed. A model-written branch (free/untrusted model) goes
   through the full untrusted-code chain first.
3. Lodewijk pushes and opens the PR; he posts the drafted text if he wants it.

## Why this shape

- Two layers: the server agent can't reach GitHub at all, and every change passes the Mac before it's public.
- No tokens or keys with write access on the server for these repos, so nothing to leak or misuse there.
- It costs Lodewijk one fetch and one push per branch, which is the point: he decides what goes public.
