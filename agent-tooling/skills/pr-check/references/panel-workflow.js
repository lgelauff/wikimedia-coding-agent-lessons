// pr-check expert panel + cross-review — Claude Code Workflow template.
// Adapt before running:
//   - SELECTED: the reviewer keys from the project config's `reviewers` map for the
//     scope flags that fired (the generalist/_always entry is always in). Every key
//     must exist in BRIEFS — an unknown key throws rather than degrading to a
//     generic review. Add a brief for a new reviewer name; do not rename one away.
//   - REF / FILES: a pinned ref or worktree the agents read from — NEVER the live
//     working tree (it may have concurrent edits).
//   - PACK: the evidence pack from step 2 (diff, gate output, scope flags).
// Run via Workflow({script: <this, adapted>}).

export const meta = {
  name: 'pr-check-panel',
  description: 'Type-matched expert review of a PR diff with a cross-review round, then synthesis',
  phases: [{ title: 'Review' }, { title: 'Cross-review' }, { title: 'Synthesize' }],
}

const REF = 'origin/<branch-or-pin>'          // adapt
const FILES = '<space-separated changed code files>'  // adapt (skip generated/image/doc files)
const PACK = '<evidence pack: diff, deterministic-gate output, scope flags>'  // adapt

const COMMON = `Review the change on ${REF} (changed files: ${FILES}).

Evidence pack (shared by every reviewer — a floor, not a ceiling):
${PACK}

Read read-only via git show/git grep/git log against ${REF}; do NOT touch the working tree (parallel agents may be editing it). You may explore beyond the diff: up to ~10 targeted reads/searches — say what you opened and why. Read each changed file in full, not just hunks; verify against the real file. Every finding cites file:line + the exact fix, and sets evidence="diff" if the diff alone shows it or evidence="repo" if you had to read outside the diff. Distinguish real bugs from style. Anything with a right answer (formatting, types, lint, test results) is the deterministic gate's job, not yours — if the gate missed such a thing, report it under gate_proposals, not as a finding.

REQUIRED second output — gate_proposals: the objective checks the gate should have owned. Each names the check, what it would have caught in THIS change, and where it belongs (test | lint | guard | scope-pattern). An empty list is allowed only if you looked and found none.`

const EVIDENCE = { type: 'string', enum: ['diff', 'repo'], description: 'diff = visible in the diff alone; repo = needed reading outside it' }
const GATE_PROPOSALS = { type: 'array', items: {
  type: 'object', additionalProperties: false, required: ['check', 'would_have_caught', 'belongs_in'],
  properties: {
    check: { type: 'string' }, would_have_caught: { type: 'string' },
    belongs_in: { type: 'string', enum: ['test', 'lint', 'guard', 'scope-pattern'] },
  },
} }

const SCHEMA = {
  type: 'object', additionalProperties: false, required: ['role', 'overall', 'findings', 'gate_proposals'],
  properties: {
    role: { type: 'string' }, overall: { type: 'string' },
    findings: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['id', 'severity', 'title', 'location', 'issue', 'recommendation', 'confidence', 'reproducible', 'evidence'],
      properties: {
        id: { type: 'string' }, severity: { type: 'string', enum: ['blocker', 'serious', 'moderate', 'minor', 'nit'] },
        title: { type: 'string' }, location: { type: 'string' }, issue: { type: 'string' },
        recommendation: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        reproducible: { type: 'string', enum: ['yes', 'no'], description: 'concrete runtime trigger?' },
        evidence: EVIDENCE,
      },
    } },
    gate_proposals: GATE_PROPOSALS,
  },
}
const CROSS = {
  type: 'object', additionalProperties: false, required: ['role', 'confirmed', 'disputed', 'missed', 'gate_proposals'],
  properties: {
    role: { type: 'string' }, confirmed: { type: 'array', items: { type: 'string' } },
    disputed: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['id', 'reason'],
      properties: { id: { type: 'string' }, reason: { type: 'string' } } } },
    missed: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['severity', 'title', 'location', 'issue', 'recommendation', 'evidence'],
      properties: { severity: { type: 'string' }, title: { type: 'string' }, location: { type: 'string' },
        issue: { type: 'string' }, recommendation: { type: 'string' }, evidence: EVIDENCE } } },
    gate_proposals: GATE_PROPOSALS,
  },
}

// Reviewer briefs keyed by the names used in the project config's `reviewers` map.
// Viewpoints, not checklists: whose perspective does this change need? Anything a
// tool could answer belongs in the deterministic gate (playbook step 1).
const BRIEFS = {
  'senior-engineer': 'You review for the person who maintains this code in a year and did not write it. Does the change do what the issue asked (not only what the prompt said)? Does it leave the code healthier, even if imperfect? Will its names, comments and tests still explain it once the author is gone? Would each new test fail without the change?',
  'accessibility': 'You review for someone using a screen reader, a keyboard only, or magnification. Walk the changed screens as that person: can they reach it, tell what it is, operate it, and hear what happened?',
  'usability': 'You review for a first-time user trying to finish a task under mild time pressure. Where would they hesitate, misread the wording, hit a dead end, or not notice that something changed?',
  'frontend-js': 'You review for whoever debugs this in a user\'s browser after it ships. What happens on the slow network, the double click, the stale tab, the failed request? Where does client state drift from what the server believes, and does the seam between this code and its API agree on shapes and validation?',
  'database': 'You review for the person who runs this migration against production data with users online. What does it lock, what does it assume about existing rows, and what happens if it has to be rolled back?',
  'ops': 'You review for the person paged at 3am after this deploys. Can they tell what changed, turn it off, and redeploy the previous version safely? What does it need from the environment that nobody wrote down?',
}

const SELECTED = ['senior-engineer']  // ← replace with the fired-flag reviewers from the config
const unknown = SELECTED.filter(k => !(k in BRIEFS))
if (unknown.length) throw new Error(`pr-check panel: no brief for reviewer(s) ${unknown.join(', ')} — add a viewpoint to BRIEFS or fix the config's reviewers map`)
const ROLES = SELECTED.map(k => ({ key: k, label: k, brief: BRIEFS[k] }))

phase('Review')
const reviews = (await parallel(ROLES.map(r => () =>
  agent(`${COMMON}\n\nVIEWPOINT (${r.label}): ${r.brief}\nReturn findings and gate_proposals; role="${r.label}", id prefix "${r.key}-". reproducible:"yes" only for bugs with a concrete runtime trigger.`,
    { label: `review:${r.key}`, phase: 'Review', schema: SCHEMA })))).filter(Boolean)

phase('Cross-review')
const all = reviews.map(rv => `### ${rv.role}\n${rv.overall}\n` + rv.findings.map(f =>
  `- [${f.id}] (${f.severity}/${f.confidence}/repro=${f.reproducible}/evidence=${f.evidence}) ${f.title} @ ${f.location}\n    ${f.issue}\n    fix: ${f.recommendation}`).join('\n')).join('\n\n')
const cross = (await parallel(ROLES.map(r => () =>
  agent(`${COMMON}\n\nVIEWPOINT (${r.label}): ${r.brief}\n\nAll experts' findings:\n${all}\n\nCross-review from your viewpoint: confirm real ids, dispute wrong/overstated (reason), add missed (with evidence), and add any gate_proposals the others missed. role="${r.label}".`,
    { label: `cross:${r.key}`, phase: 'Cross-review', schema: CROSS })))).filter(Boolean)

phase('Synthesize')
const gateProposals = [...reviews, ...cross].flatMap(x => x.gate_proposals.map(g => ({ ...g, from: x.role })))
const crossText = cross.map(c => `### ${c.role}\nconfirmed: ${c.confirmed.join(', ') || '-'}\ndisputed: ${c.disputed.map(d => `${d.id} (${d.reason})`).join('; ') || '-'}\nmissed: ${c.missed.map(m => `(${m.severity}/evidence=${m.evidence}) ${m.title} @ ${m.location}`).join('; ') || '-'}`).join('\n\n')
const gateText = gateProposals.map(g => `- [${g.from}] ${g.check} → would have caught: ${g.would_have_caught} → belongs in: ${g.belongs_in}`).join('\n') || '-'
const report = await agent(
  `Consolidate this panel + cross-review for a PR gate.\n\nFINDINGS:\n${all}\n\nCROSS-REVIEW:\n${crossText}\n\nGATE PROPOSALS:\n${gateText}\n\n` +
  `Output: (1) cross-confirmed must-fix by severity with file:line+fix, marking reproducible:yes ones and each finding's evidence=diff|repo; (2) disputed/false-positives knocked down with why; (3) over-claims/gaps; (4) gate proposals, deduped (check → what it would have caught → where it belongs); (5) one-line panel verdict. Don't invent agreement.`,
  { label: 'synthesize', phase: 'Synthesize' })

const findings = reviews.flatMap(r => r.findings)
return {
  report,
  reproducible: findings.filter(f => f.reproducible === 'yes').map(f => ({ id: f.id, title: f.title, location: f.location })),
  evidence: { diff: findings.filter(f => f.evidence === 'diff').length, repo: findings.filter(f => f.evidence === 'repo').length },
  gate_proposals: gateProposals,
  reviewers: reviews.length,
}
