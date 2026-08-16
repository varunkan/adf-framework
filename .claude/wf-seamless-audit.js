export const meta = {
  name: 'adf-seamless-build-audit',
  description: 'Audit ADF prompt-to-app pipeline + preview UX; design and adversarially verify the highest-leverage fixes to reach a Lovable/Emergent-class seamless build experience',
  phases: [
    { title: 'Map' },
    { title: 'Design' },
    { title: 'Verify' },
  ],
}

const ROOT = '/Users/varunkumar/adf-framework'

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    area: { type: 'string' },
    summary: { type: 'string' },
    friction_points: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          title: { type: 'string' },
          detail: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } },
          severity: { type: 'string', enum: ['blocker', 'high', 'medium', 'low'] },
        },
        required: ['title', 'detail', 'files', 'severity'],
      },
    },
    proposed_fixes: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          title: { type: 'string' },
          what: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } },
          impact: { type: 'string', enum: ['high', 'medium', 'low'] },
          effort: { type: 'string', enum: ['small', 'medium', 'large'] },
        },
        required: ['title', 'what', 'files', 'impact', 'effort'],
      },
    },
  },
  required: ['area', 'summary', 'friction_points', 'proposed_fixes'],
}

phase('Map')
const MAP = [
  {
    label: 'pipeline-latency',
    prompt: 'You are auditing the ADF build pipeline at ' + ROOT + ' for END-TO-END LATENCY from "user types a prompt" to "working app exists". Read deeply: tools/orchestration_server/bin/server.dart (POST /features, /features/<id>/commands, /autopilot, /run); tools/orchestration_server/lib/agent_crew.dart and/or autopilot.dart (phases 1-6 deterministic crew); tools/orchestration_server/lib/phase_runner.dart (_spawnAgent, ORCH_RUNNER_TIMEOUT_SEC, self-heal); scripts/orch/agent_runner.py (LLM calls, file writes, test run, headroom). Produce a precise ordered understanding from prompt submit to "app files written + tests pass", with a realistic latency estimate per step and the friction at each. Identify the CRITICAL PATH and the single biggest latency sink. Then list friction_points and concrete proposed_fixes (with file paths) that make this dramatically faster or feel faster (streaming, parallelism, optimistic UI, caching, skipping redundant work). Focus on SPEED and PERCEIVED speed.',
  },
  {
    label: 'preview-render',
    prompt: 'You are auditing whether ADF gives a LOVABLE-STYLE live preview at ' + ROOT + ': when a user builds an app, do they actually SEE the built app render (like Lovable/v0/bolt.new show the working app in an iframe that updates), or only spec text/logs/status? Read: tools/orchestration_dashboard/lib/widgets/live_preview_panel.dart (it currently shows requirement text, a code excerpt as monospace, and a previewUrl shown only as selectable text / copied to clipboard - it does NOT render the app inline); any preview service in tools/orchestration_server/lib/ (grep preview_service.dart, ORCH_PREVIEW_BUILD, buildPreview, preview_url); server.dart routes serving generated apps (grep apps/, index.html, static). Generated apps live at apps/<feature-id>/{server.py,index.html}. KEY question: how do we render the ACTUAL built app live inline in the dashboard (Flutter web HtmlElementView + iframe pointing at a served app URL, auto-refresh on build complete)? Detail what the preview shows now, what endpoint/service would serve apps/<id>/index.html, and the concrete fix with file paths, impact, effort.',
  },
  {
    label: 'feedback-stream',
    prompt: 'You are auditing the SECOND-BY-SECOND feedback a user sees in the ADF dashboard while a build runs at ' + ROOT + '. Recent fixes already added: durable run-outcome bubbles, a lossless chat merge, and a "Still building - Ns elapsed" status. Read: tools/orchestration_dashboard/lib/screens/feature_detail_screen.dart (_statusBar, _mergedConversation, polling cadence, autopilot); tools/orchestration_dashboard/lib/widgets/agent_conversation_view.dart (live trace polling, PlainThoughtView, _WaitingForThoughts); tools/orchestration_dashboard/lib/widgets/plain_thought_view.dart and trace polling in api_client.dart; how traces stream from the server (trace_writer.dart, GET /traces). Build a perceived-progress understanding of exactly what the user sees from submit to done, and find the DEAD-AIR gaps, jank (relayout, flicker), confusing transitions, and anything that feels slow or broken vs Lovable streaming. List friction_points + concrete proposed_fixes (file paths, impact, effort) to make feedback feel continuous and alive (streamed code/tokens, typewriter, file-by-file appearance, progress mapped to real work).',
  },
  {
    label: 'lovable-benchmark',
    prompt: 'Research the UX that makes modern prompt-to-app builders feel instant and seamless: Lovable, Emergent, Vercel v0, bolt.new, Replit Agent. Use web search. Identify the concrete UX PRIMITIVES that create the "100x smoother" feel: live-rendering iframe that updates as code is written, streaming code/diffs, file tree materializing, one-box conversational iteration ("change the header color" -> instant update), hot reload, optimistic feedback, inline error self-heal shown to the user, shareable preview URL, zero setup. For EACH primitive, state whether a local ADF (Flutter dashboard + Dart API + python agent_runner writing apps/<id>/{server.py,index.html} at ' + ROOT + ') could realistically implement it and how. Return friction_points = the primitives ADF most likely lacks, and proposed_fixes = the specific ones to build first for maximum wow, ranked by impact. Be concrete and implementation-oriented, not generic.',
  },
]

const mapResults = await parallel(
  MAP.map((m) => () => agent(m.prompt, { label: m.label, phase: 'Map', schema: FINDINGS_SCHEMA }))
)
const maps = mapResults.filter(Boolean)
log('Map done: ' + maps.length + '/4 areas.')

const allFixes = maps.flatMap((m) => (m.proposed_fixes || []).map((f) => ({ title: f.title, what: f.what, files: f.files || [], impact: f.impact, effort: f.effort, area: m.area })))

function digestOne(m) {
  const fr = (m.friction_points || []).map((p) => '[' + p.severity + '] ' + p.title).join('; ')
  const fx = (m.proposed_fixes || []).map((f) => f.title + ' (' + f.impact + '/' + f.effort + ')').join('; ')
  return '### ' + m.area + '\n' + (m.summary || '') + '\nFriction: ' + fr + '\nFixes: ' + fx
}
const frictionDigest = maps.map(digestOne).join('\n\n')

phase('Design')
const ANGLES = [
  { key: 'perceived-speed', lens: 'PERCEIVED SPEED first - make every second feel productive: streaming, optimistic UI, progress mapped to real work, kill all dead air. Same wall-clock, but FEELS 100x smoother.' },
  { key: 'live-render', lens: 'LIVE RENDER first - the single biggest Lovable differentiator is SEEING the real app materialize and update in an inline preview. Prioritize rendering the actual built app and auto-refreshing it.' },
  { key: 'iteration-loop', lens: 'ITERATION LOOP first - seamless conversational iteration: type "make the button blue" and watch the app change in seconds, chat as the single control surface. Prioritize the tight edit->rebuild->re-render loop.' },
]
const PLAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    angle: { type: 'string' },
    thesis: { type: 'string' },
    ranked_changes: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          title: { type: 'string' },
          what: { type: 'string' },
          why_it_matters: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } },
          impact: { type: 'string', enum: ['high', 'medium', 'low'] },
          effort: { type: 'string', enum: ['small', 'medium', 'large'] },
        },
        required: ['title', 'what', 'why_it_matters', 'files', 'impact', 'effort'],
      },
    },
  },
  required: ['angle', 'thesis', 'ranked_changes'],
}
const planResults = await parallel(
  ANGLES.map((a) => () => agent(
    'You are designing how to make ADF prompt-to-app feel Lovable/Emergent-class (100x smoother) at ' + ROOT + '. Your lens: ' + a.lens + '\n\nAudit of the current pipeline + preview + feedback + benchmark:\n\n' + frictionDigest + '\n\nProduce a focused, RANKED set of concrete changes through your lens - each with what to do, why it matters for the felt experience, file paths, impact, effort. Prefer the few highest-leverage changes. Be specific to this codebase (Flutter dashboard, Dart API, python agent_runner writing apps/<id>/).',
    { label: 'design:' + a.key, phase: 'Design', schema: PLAN_SCHEMA }
  ))
)
const plans = planResults.filter(Boolean)
log('Design panel: ' + plans.length + '/3 angles.')

const candidates = [
  ...allFixes.map((f) => ({ title: f.title, what: f.what, files: f.files || [], impact: f.impact, effort: f.effort, source: 'map:' + f.area })),
  ...plans.flatMap((p) => (p.ranked_changes || []).map((c) => ({ title: c.title, what: c.what, files: c.files || [], impact: c.impact, effort: c.effort, source: 'design:' + p.angle }))),
]

phase('Verify')
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    title: { type: 'string' },
    already_implemented: { type: 'boolean' },
    is_correct_and_feasible: { type: 'boolean' },
    real_impact: { type: 'string', enum: ['high', 'medium', 'low'] },
    verdict: { type: 'string', enum: ['build-now', 'build-later', 'drop'] },
    reason: { type: 'string' },
    implementation_notes: { type: 'string' },
  },
  required: ['title', 'already_implemented', 'is_correct_and_feasible', 'real_impact', 'verdict', 'reason', 'implementation_notes'],
}
const verdictResults = await parallel(
  candidates.map((c) => () => agent(
    'Adversarially verify this proposed ADF improvement against the ACTUAL codebase at ' + ROOT + '. Read the named files before judging. Be skeptical - default to dropping vague or already-done items.\n\nProposed change: ' + c.title + '\nWhat: ' + c.what + '\nClaimed files: ' + ((c.files || []).join(', ') || '(none given - find them)') + '\nSource lens: ' + c.source + '\n\nDetermine: (1) is it ALREADY implemented? (2) is it correct and feasible in THIS codebase? (3) REAL impact on making the build feel Lovable-class? (4) verdict: build-now (high impact, feasible, not done) / build-later / drop. Give concrete implementation_notes (exact files, functions, approach) if build-now.',
    { label: 'verify:' + (c.title || 'fix').slice(0, 26), phase: 'Verify', schema: VERDICT_SCHEMA }
  ))
)
const verdicts = verdictResults.filter(Boolean)

const rank = { 'build-now': 3, 'build-later': 2, 'drop': 1 }
const byTitle = new Map()
for (const v of verdicts) {
  const key = (v.title || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().slice(0, 40)
  const prev = byTitle.get(key)
  if (!prev || rank[v.verdict] > rank[prev.verdict]) byTitle.set(key, v)
}
const mergedV = [...byTitle.values()]
const impactRank = { high: 3, medium: 2, low: 1 }
const buildNow = mergedV.filter((v) => v.verdict === 'build-now' && !v.already_implemented).sort((a, b) => impactRank[b.real_impact] - impactRank[a.real_impact])
const buildLater = mergedV.filter((v) => v.verdict === 'build-later' && !v.already_implemented)
log('Verify done: ' + buildNow.length + ' build-now, ' + buildLater.length + ' build-later.')

return { build_now: buildNow, build_later: buildLater, maps, plans }
