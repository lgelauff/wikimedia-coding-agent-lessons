/**
 * agent-tooling — OpenCode adapter.
 *
 * The thin half of the agnostic/adapter split described in agent-tooling/ARCHITECTURE.md.
 * Every decision lives in a Python policy executable that knows nothing about any agent's
 * event format. This file only translates: it feeds the host event to the policy, reads
 * the exit code, and throws when the policy says block.
 *
 * Two hooks:
 *
 *   shell.env            inject the environment every skill depends on.
 *   tool.execute.before  run the policy guards.
 *
 * Why shell.env and not config: OpenCode's `{env:VAR}` substitution applies to config
 * values only, never to the shell a skill command runs in. Skill bodies are Bash tool
 * calls, made later, in a shell that never saw the config. Injecting here is the only
 * mechanism that reaches them.
 *
 * ── Runtime discipline ────────────────────────────────────────────────────────────
 *
 * **Use only Node built-ins. Never a Bun global.**
 *
 * An earlier version of this file used `Bun.spawn` and `Bun.file`, on the reasoning that
 * the docs type the plugin input as `$: BunShell`. That inference was wrong. The plugin
 * is loaded in a runtime where `Bun` is undefined, and the failure was not contained: the
 * module threw at load, the plugin never registered, and **every bash tool call in the
 * session failed with `Bun is not defined`**. A broken adapter did not degrade — it took
 * out the tool.
 *
 * So: `node:child_process` and `node:fs` only. They exist under Bun too, which makes this
 * file work either way rather than betting on one.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Where the plugin's own root is.
//
// This cannot come from the environment: `shell.env` is what puts it into the shell, so
// reading it there is circular, and the plugin process is spawned by OpenCode, not by a
// shell that ever had it set. It is derived from the file's own location instead.
//
// The file lives at `<root>/adapters/opencode/plugins/agent-tooling.js`, so the root is
// THREE levels up: plugins -> opencode -> adapters -> agent-tooling. Getting this wrong
// is silent in both directions: the injected AGENT_TOOLING_ROOT points at the wrong
// directory, and every policy path fails existsSync, so the guards allow everything
// while appearing to be installed. Verified with the path laid out, not by counting.
//
// import.meta.url resolves through OpenCode's symlink to the real file, which is why one
// canonical copy under version control can serve both machines. The env var remains a
// fallback for a copied file.
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.AGENT_TOOLING_ROOT || resolve(HERE, "..", "..", "..");

/**
 * The single canonical User-Agent, defined once.
 *
 * The source-collection package previously checked robots.txt as one identity and then
 * fetched as another, while also leaking an email address on every request. Putting the
 * value here means every script that reads it reports the same identity the robots check
 * used. Scripts should read WIKIMEDIA_UA rather than define their own.
 */
const UA =
  "WikimediaAnalysis/1.0 (personal research project; https://github.com/lgelauff/wikimedia-analysis)";

/**
 * Run a policy executable; resolve to the reason when it blocks, or null when it allows.
 *
 * A policy that exits non-zero is not an error — it is a decision. So spawn failures are
 * resolved to null (fail-open on infrastructure, not on policy) while a genuine non-zero
 * exit returns the reason and blocks. `policy` never rejects.
 */
function runPolicy(script, args) {
  return new Promise((done) => {
    const path = `${ROOT}/policies/${script}`;
    if (!existsSync(path)) return done(null); // an absent policy is not a block

    let child;
    try {
      child = spawn("python3", [path, ...args], { stdio: ["ignore", "pipe", "pipe"] });
    } catch {
      return done(null); // could not run the policy: do not block the session on it
    }

    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("error", () => done(null)); // python3 missing, etc.
    child.on("close", (code) => {
      if (code === 0) return done(null);
      done((out || err || `blocked by ${script}`).trim());
    });
  });
}

/**
 * A policy decision, as distinct from a bug in this file.
 *
 * The distinction has to be explicit. Classifying by message text means a regex decides
 * whether a block reaches the agent or a bug blocks the session — and a misfire in either
 * direction is bad: a swallowed block is a guard that does not guard, a propagated bug is
 * a plugin that takes out the tool.
 */
class PolicyBlock extends Error {
  constructor(reason) {
    super(reason);
    this.name = "PolicyBlock";
    this.policyBlock = true;
  }
}

/**
 * Record a secret-free command shape for the permission-ergonomics report.
 *
 * Fire-and-forget and detached: instrumentation must never add latency to, or break, a
 * shell call. The shape logic and the log format live in scripts/bash_shape.py so they
 * are shared and testable rather than reimplemented here.
 */
function recordShape(command) {
  try {
    const child = spawn("python3", [`${ROOT}/scripts/bash_shape.py`, "--record", command], {
      stdio: "ignore",
      detached: true,
    });
    child.on("error", () => {});
    child.unref();
  } catch {
    /* never let instrumentation break the tool */
  }
}

/** Which tool invocations get which guard. First block wins. */
function guardsFor(tool, args) {
  switch (tool) {
    case "bash": {
      const command = String(args?.command ?? "");
      if (!command) return [];
      return [["is_ssh_command.py", [command]]];
    }
    case "webfetch": {
      // `webfetch` is Action-only in 1.18.30, so the mandated-services allow-list
      // cannot live in config as a domain map. The policy reads the registry and
      // denies an unlisted host with an explicit-request message. Config keeps
      // `webfetch: "ask"`, so a mandated host still prompts and a plugin load
      // failure degrades to a prompt rather than to open network access.
      const url = String(args?.url ?? "");
      if (!url) return [];
      return [["webfetch_mandated.py", [url]]];
    }
    default:
      return [];
  }
}

/**
 * Hooks, each wrapped so a failure inside one cannot break the session.
 *
 * The load-time version of this bug was worse than a failed hook: the module threw during
 * registration, and OpenCode's loader is not isolated, so **every bash call in the session
 * died** with the plugin's error. A guard that takes out the tool is worse than no guard.
 */
export const AgentTooling = async () => ({
  "shell.env": async (_input, output) => {
    try {
      if (ROOT) output.env.AGENT_TOOLING_ROOT = ROOT;
      output.env.WIKIMEDIA_UA = UA;
    } catch {
      /* never let env injection break a shell call */
    }
  },

  "tool.execute.before": async (input, output) => {
    if (input.tool === "bash") recordShape(String(output.args?.command ?? ""));
    for (const [script, args] of guardsFor(input.tool, output.args)) {
      let reason;
      try {
        reason = await runPolicy(script, args);
      } catch {
        continue; // infrastructure failure: do not block on it
      }
      if (reason) {
        // Only a policy decision propagates. OpenCode plugins cannot answer "ask", so
        // anything needing the user's judgement belongs in a static permission pattern.
        throw new PolicyBlock(reason);
      }
    }
  },
});
