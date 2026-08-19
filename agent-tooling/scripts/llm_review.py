#!/usr/bin/env python3
"""
llm_review.py — send code files + a reviewer persona to Mistral for analysis.

Designed to be called from any repository. The persona and task are passed
as arguments so this script is fully reusable across projects.

Usage:
    python ~/.claude/scripts/llm_review.py \
        --files path/to/file1.py path/to/file2.sql \
        --persona ~/.claude/personas/db_expert.md \
        --task "Review the SQL queries for correctness and performance." \
        [--model auto|small|nemo|large] \
        [--output results.md]

    # Inline persona (no file needed):
    python ~/.claude/scripts/llm_review.py \
        --files labs.py \
        --persona "You are a senior database engineer. Be concise and specific." \
        --task "Are there any performance or correctness issues?"

Model auto-selection (by estimated token count):
    < 20k tokens  →  mistral-small-latest   (32k ctx,  cheapest)
    20k–80k       →  open-mistral-nemo       (128k ctx, cheap)
    > 80k         →  mistral-large-latest    (128k ctx, most capable)

API key: set MISTRAL_API_KEY environment variable.
"""

import argparse
import datetime
import os
import sys


def _requests():
    """Import lazily so --help works without the dependency installed."""
    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. Run: pip install requests",
              file=sys.stderr)
        sys.exit(1)
    return requests


MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# (model_id, context_token_limit)
MODELS = {
    "small": ("mistral-small-latest", 32_000),
    "nemo":  ("open-mistral-nemo",   128_000),
    "large": ("mistral-large-latest", 128_000),
}

# Rough estimate: 1 token ≈ 4 characters
_CHARS_PER_TOKEN = 4


def estimate_tokens(text):
    return len(text) // _CHARS_PER_TOKEN


def select_model(estimated_tokens, hint="auto"):
    if hint != "auto":
        return MODELS[hint]
    if estimated_tokens < 20_000:
        return MODELS["small"]
    elif estimated_tokens < 80_000:
        return MODELS["nemo"]
    else:
        return MODELS["large"]


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        print(f"WARNING: could not read {path}: {e}", file=sys.stderr)
        return None


def build_context(paths):
    parts = []
    for path in paths:
        content = read_file(path)
        if content is not None:
            # Use the extension to pick a fenced code language hint
            ext = os.path.splitext(path)[1].lstrip(".")
            parts.append(f"### {path}\n\n```{ext}\n{content}\n```")
    return "\n\n".join(parts)


def load_persona(persona_arg):
    """Accept a file path or an inline string."""
    if os.path.isfile(persona_arg):
        content = read_file(persona_arg)
        if content is not None:
            return content
    return persona_arg


def call_mistral(system_prompt, user_prompt, model_name, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    resp = _requests().post(MISTRAL_API_URL, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage


def main():
    parser = argparse.ArgumentParser(
        description="Send code files + a reviewer persona to Mistral.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--files", nargs="+", required=True,
        help="One or more file paths to include as context",
    )
    parser.add_argument(
        "--persona", required=True,
        help="Path to a persona file (.md/.txt) or an inline persona string",
    )
    parser.add_argument(
        "--task", required=True,
        help="The review question or task to ask the reviewer",
    )
    parser.add_argument(
        "--model", default="auto", choices=["auto", "small", "nemo", "large"],
        help="Model to use (default: auto-select based on context size)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Write result to this file in addition to stdout",
    )
    args = parser.parse_args()

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    persona = load_persona(args.persona)
    file_context = build_context(args.files)

    if not file_context:
        print("ERROR: no file content could be read.", file=sys.stderr)
        sys.exit(1)

    user_prompt = f"{args.task}\n\n## Files\n\n{file_context}"
    est_tokens = estimate_tokens(persona + user_prompt)
    model_name, ctx_limit = select_model(est_tokens, args.model)

    print(f"Estimated tokens : ~{est_tokens:,}", file=sys.stderr)
    print(f"Model selected   : {model_name} (limit: {ctx_limit:,})", file=sys.stderr)

    if est_tokens > ctx_limit * 0.85:
        print(
            f"WARNING: estimated tokens ({est_tokens:,}) exceed 85% of the model's "
            f"context limit ({ctx_limit:,}). Consider --model large or fewer files.",
            file=sys.stderr,
        )

    print("Calling Mistral API...", file=sys.stderr)
    result, usage = call_mistral(persona, user_prompt, model_name, api_key)

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    file_list = ", ".join(args.files)
    header = (
        f"# Mistral Review — {now}\n\n"
        f"**Model:** {model_name}  \n"
        f"**Files:** {file_list}  \n"
        f"**Task:** {args.task}  \n"
        f"**Tokens used:** input={usage.get('prompt_tokens', '?')} "
        f"output={usage.get('completion_tokens', '?')}  \n\n"
        f"---\n\n"
    )
    output = header + result

    print(output)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nResult written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
