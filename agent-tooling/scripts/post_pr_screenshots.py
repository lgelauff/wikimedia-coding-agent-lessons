#!/usr/bin/env python3
"""Post screenshots to a PR as a rendered comment.

GitHub comment markdown needs images at a URL (gh can't attach binaries). For a
PUBLIC repo this pushes the images to a dedicated **assets branch** (so the PR
branch stays clean) and embeds their raw.githubusercontent URLs in a comment.

SAFETY: this pushes to the remote AND posts a public comment, so it is opt-in:
  • default is --dry-run: prints the comment markdown and the planned uploads,
    touches nothing.
  • it acts only with --confirm. (Honors "never push / never comment without
    explicit approval".)

Requires a PUBLIC repo (raw URLs won't render for private repos in others'
view). Aborts with a note if the repo is private.

Usage:
  post_pr_screenshots.py --pr 174 \
    --image "Arguments tab=probe-args.png" --image "Vote flow=probe-vote.png" \
    --intro "browser-verify on the arguments-tab redesign" --confirm
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile


def sh(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def repo_slug():
    out = sh(["gh", "repo", "view", "--json", "nameWithOwner,visibility"]).stdout
    d = json.loads(out)
    return d["nameWithOwner"], d["visibility"]


def build_markdown(intro, images, repo, branch, pr):
    lines = [f"## 📸 Screenshots — {intro}".rstrip(), ""]
    for label, fname in images:
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/pr-{pr}/{fname}"
        lines += [f"**{label}**", "", f"![{label}]({url})", ""]
    lines.append("<sub>Posted by agent-tooling browser-verify. Images live on the "
                 f"`{branch}` branch.</sub>")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", required=True)
    ap.add_argument("--image", action="append", default=[], metavar="LABEL=PATH",
                    help="repeatable; caption=imagefile")
    ap.add_argument("--intro", default="screenshots")
    ap.add_argument("--assets-branch", default="pr-screenshots")
    ap.add_argument("--confirm", action="store_true",
                    help="actually push images + post the comment (else dry-run)")
    a = ap.parse_args()

    images = []
    for spec in a.image:
        if "=" not in spec:
            sys.exit(f"--image must be LABEL=PATH, got: {spec}")
        label, path = spec.split("=", 1)
        if not os.path.isfile(path):
            sys.exit(f"image not found: {path}")
        images.append((label.strip(), os.path.basename(path), path))

    if not images:
        sys.exit("no --image given")

    repo, vis = repo_slug()
    if vis != "PUBLIC":
        sys.exit(f"refusing: {repo} is {vis}. Raw image URLs only render for PUBLIC repos.")

    md_images = [(label, fname) for label, fname, _ in images]
    md = build_markdown(a.intro, md_images, repo, a.assets_branch, a.pr)

    if not a.confirm:
        print("DRY RUN (no push, no comment). Re-run with --confirm to post.\n")
        print(f"Would push {len(images)} image(s) to {repo}@{a.assets_branch}:/pr-{a.pr}/")
        for _, fname, src in images:
            print(f"  {src}  ->  pr-{a.pr}/{fname}")
        print("\n--- comment markdown ---\n" + md)
        return

    # Push images to the assets branch via an isolated worktree (don't touch the
    # current working branch / tree).
    root = sh(["git", "rev-parse", "--show-toplevel"]).stdout.strip()
    sh(["git", "fetch", "origin", a.assets_branch], cwd=root, check=False)
    with tempfile.TemporaryDirectory() as wt:
        sh(["git", "worktree", "add", "--detach", wt], cwd=root)
        try:
            if sh(["git", "checkout", a.assets_branch], cwd=wt, check=False).returncode != 0:
                sh(["git", "checkout", "--orphan", a.assets_branch], cwd=wt)
                sh(["git", "rm", "-rf", "--ignore-unmatch", "."], cwd=wt, check=False)
            dest = os.path.join(wt, f"pr-{a.pr}")
            os.makedirs(dest, exist_ok=True)
            for _, fname, src in images:
                sh(["cp", src, os.path.join(dest, fname)])
            sh(["git", "add", "-A"], cwd=wt)
            sh(["git", "commit", "-m", f"screenshots: PR #{a.pr}"], cwd=wt)
            sh(["git", "push", "-u", "origin", a.assets_branch], cwd=wt)
        finally:
            sh(["git", "worktree", "remove", "--force", wt], cwd=root, check=False)

    # Post the comment; gh reads the body from stdin via --body-file -.
    subprocess.run(["gh", "pr", "comment", str(a.pr), "--body-file", "-"],
                   input=md, text=True, cwd=root, check=True)
    print(f"Posted screenshot comment to PR #{a.pr} (images on {a.assets_branch}).")


if __name__ == "__main__":
    main()
