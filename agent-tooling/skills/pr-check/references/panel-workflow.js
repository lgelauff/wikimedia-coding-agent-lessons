// pr-check expert panel + cross-review — Claude Code Workflow template.
// Adapt before running:
//   - ROLES: keep only the reviewers selected from the project config's `reviewers`
//     map for the scope flags that fired (the generalist/_always entry is always in).
//   - REF / FILES: a pinned ref or worktree the agents read from — NEVER the live
//     working tree (it may have concurrent edits).
// Run via Workflow({script: <this, adapted>}).

export const meta = {
  name: 'pr-check-panel',
  description: 'Type-matched expert review of a PR diff with a cross-review round, then synthesis',
  phases: [{ title: 'Review' }, { title: 'Cross-review' }, { title: 'Synthesize' }],
}

const REF = 'origin/<branch-or-pin>'          // adapt
const FILES = '<space-separated changed code files>'  // adapt (skip generated/image/doc files)

const COMMON = `Review the change on ${REF} (changed files: ${FILES}). Read read-only via git show/git grep against ${REF}; do NOT touch the working tree (parallel agents may be editing it). Read each changed file in full, not just hunks; verify against the real file. Every finding cites file:line + the exact fix. Distinguish real bugs from style. Flag anything where new behavior could break a user-facing flow.`

const SCHEMA = {
  type: 'object', additionalProperties: false, required: ['role', 'overall', 'findings'],
  properties: {
    role: { type: 'string' }, overall: { type: 'string' },
    findings: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['id', 'severity', 'title', 'location', 'issue', 'recommendation', 'confidence', 'reproducible'],
      properties: {
        id: { type: 'string' }, severity: { type: 'string', enum: ['blocker', 'serious', 'moderate', 'minor', 'nit'] },
        title: { type: 'string' }, location: { type: 'string' }, issue: { type: 'string' },
        recommendation: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        reproducible: { type: 'string', enum: ['yes', 'no'], description: 'concrete runtime trigger?' },
      },
    } },
  },
}
const CROSS = {
  type: 'object', additionalProperties: false, required: ['role', 'confirmed', 'disputed', 'missed'],
  properties: {
    role: { type: 'string' }, confirmed: { type: 'array', items: { type: 'string' } },
    disputed: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['id', 'reason'],
      properties: { id: { type: 'string' }, reason: { type: 'string' } } } },
    missed: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['severity', 'title', 'location', 'issue', 'recommendation'],
      properties: { severity: { type: 'string' }, title: { type: 'string' }, location: { type: 'string' },
        issue: { type: 'string' }, recommendation: { type: 'string' } } } },
  },
}

// Reviewer briefs keyed by the names used in the project config's `reviewers` map.
const BRIEFS = {
  'senior-engineer': 'Correctness, regressions, maintainability, error paths, does-the-diff-match-its-claims.',
  'accessibility': 'WCAG 2.1/2.2 AA: roles/states, focus management, name/role/value, contrast, hit-targets, heading order, reduced-motion, live regions. Flag rules the code still violates.',
  'usability': 'Does the change help real users (incl. AT users) complete tasks; confusion, dead-ends, state not reflected, regressions.',
  'frontend-js': 'CSP/nonce, event wiring, null guards, throw paths, navigation/state bugs, web-component/proxy interaction, no leaked globals.',
  'database': 'Schema, migration chain head, locking, query correctness, N+1, nullability.',
  'ops': 'Deploy script, envvars, migration mode, idempotency, no secrets leaked.',
}

// SELECTED is built by the skill from the config; example fallback:
const SELECTED = ['senior-engineer']  // ← replace with the fired-flag reviewers
const ROLES = SELECTED.map(k => ({ key: k, label: k, brief: BRIEFS[k] || 'General review.' }))

phase('Review')
const reviews = (await parallel(ROLES.map(r => () =>
  agent(`${COMMON}\n\nROLE (${r.label}): ${r.brief}\nReturn findings; role="${r.label}", id prefix "${r.key}-". reproducible:"yes" only for bugs with a concrete runtime trigger.`,
    { label: `review:${r.key}`, phase: 'Review', schema: SCHEMA })))).filter(Boolean)

phase('Cross-review')
const all = reviews.map(rv => `### ${rv.role}\n${rv.overall}\n` + rv.findings.map(f =>
  `- [${f.id}] (${f.severity}/${f.confidence}/repro=${f.reproducible}) ${f.title} @ ${f.location}\n    ${f.issue}\n    fix: ${f.recommendation}`).join('\n')).join('\n\n')
const cross = (await parallel(ROLES.map(r => () =>
  agent(`${COMMON}\n\nROLE (${r.label}): ${r.brief}\n\nAll experts' findings:\n${all}\n\nCross-review via your lens: confirm real ids, dispute wrong/overstated (reason), add missed. role="${r.label}".`,
    { label: `cross:${r.key}`, phase: 'Cross-review', schema: CROSS })))).filter(Boolean)

phase('Synthesize')
const crossText = cross.map(c => `### ${c.role}\nconfirmed: ${c.confirmed.join(', ') || '-'}\ndisputed: ${c.disputed.map(d => `${d.id} (${d.reason})`).join('; ') || '-'}\nmissed: ${c.missed.map(m => `(${m.severity}) ${m.title} @ ${m.location}`).join('; ') || '-'}`).join('\n\n')
const report = await agent(
  `Consolidate this panel + cross-review for a PR gate.\n\nFINDINGS:\n${all}\n\nCROSS-REVIEW:\n${crossText}\n\n` +
  `Output: (1) cross-confirmed must-fix by severity with file:line+fix, marking reproducible:yes ones; (2) disputed/false-positives knocked down with why; (3) over-claims/gaps; (4) one-line panel verdict. Don't invent agreement.`,
  { label: 'synthesize', phase: 'Synthesize' })

return { report, reproducible: reviews.flatMap(r => r.findings).filter(f => f.reproducible === 'yes').map(f => ({ id: f.id, title: f.title, location: f.location })), reviewers: reviews.length }
