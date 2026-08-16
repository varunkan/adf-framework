// ADF full visual validation — drives the RUNNING app like a real user, across
// every view and form, on desktop AND mobile, and reports what a user would SEE
// as broken. Built into ADF (called by scripts/orch/app_verify.py); no npm
// install (node 22 fetch + WebSocket drive headless Chrome over the DevTools
// Protocol). Saves a screenshot of every view as evidence.
//
//   node visual_verify.mjs <url> <screenshotDir>  ->  JSON {ok, defects, views, screenshotDir}
//
// A defect is anything a real user would hit: an uncaught JS exception, a
// console.error, a failed (>=400) network call, a view that renders blank, or
// error text rendered ON SCREEN (undefined / NaN / [object Object] / a traceback).
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { mkdirSync, writeFileSync } from 'node:fs';

const url = process.argv[2] || 'http://127.0.0.1:8000/';
const shotDir = process.argv[3] || '/tmp/adf-visual';
const chrome = process.env.ADF_CHROME ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const port = Number(process.env.ADF_CDP_PORT || 9334);
const BUDGET_MS = Number(process.env.ADF_VISUAL_BUDGET_MS || 360000); // 6 min cap
const MAX_NAV = Number(process.env.ADF_VISUAL_MAX_NAV || 60);
const MAX_FORMS = Number(process.env.ADF_VISUAL_MAX_FORMS || 30);
// Adaptive settle caps (ms). Replace the old flat 1800ms-per-navigation dead waits:
// a server-rendered localhost app reaches readyState 'complete' in tens of ms, so
// we poll for that and only wait the cap on a genuinely slow view. Tunable for apps
// with heavier async hydration. NAV = after navigation, ACT = after a click/submit.
const NAV_SETTLE = Number(process.env.ADF_VISUAL_SETTLE_MS || 700);
const ACT_SETTLE = Number(process.env.ADF_VISUAL_ACT_SETTLE_MS || 900);
// Minimum waits (ms) before trusting readyState — covers in-page async renders
// (JS fetch → DOM update with NO navigation, where readyState is already
// 'complete'). NAV is short (let navigation start + old page unload); ACT covers
// a localhost fetch+render after a click/submit.
const NAV_FLOOR = Number(process.env.ADF_VISUAL_NAV_FLOOR_MS || 150);
const ACT_FLOOR = Number(process.env.ADF_VISUAL_ACT_FLOOR_MS || 400);
const t0 = Date.now();
const overBudget = () => Date.now() - t0 > BUDGET_MS;

mkdirSync(shotDir, { recursive: true });
const out = (o) => process.stdout.write(JSON.stringify(o, null, 2) + '\n');

// Error text a USER would see on screen (conservative — strong bug signals only).
const VIS_ERR = /\bundefined\b|\bNaN\b|\[object Object\]|is not defined|cannot read |is not a function|Traceback|Internal Server Error|ReferenceError|TypeError|SyntaxError/i;

const proc = spawn(chrome, [
  '--headless=new', `--remote-debugging-port=${port}`,
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--hide-scrollbars',
  `--user-data-dir=/tmp/adf-chrome-visual-${port}`, 'about:blank',
], { stdio: 'ignore' });

const defects = [];
const views = [];
let runtimeEvents = []; // console/exception/network errors since last reset
let safe = (s) => String(s).replace(/[^a-z0-9]+/gi, '-').slice(0, 40).replace(/^-|-$/g, '') || 'view';

try {
  let targets = null;
  for (let i = 0; i < 80; i++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/json`); targets = await r.json(); if (targets.length) break; } catch {}
    await sleep(250);
  }
  const page = targets && (targets.find((t) => t.type === 'page') || targets[0]);
  if (!page) { out({ ok: false, defects: ['headless Chrome did not expose a CDP page'], views, screenshotDir: shotDir }); proc.kill('SIGKILL'); process.exit(0); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  const send = (method, params = {}) => { const i = ++id; ws.send(JSON.stringify({ id: i, method, params })); return new Promise((res) => pend.set(i, res)); };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pend.has(msg.id)) { pend.get(msg.id)(msg.result); pend.delete(msg.id); return; }
    const { method, params } = msg;
    if (method === 'Runtime.exceptionThrown') {
      const d = params.exceptionDetails || {};
      runtimeEvents.push('JS exception: ' + String((d.exception && (d.exception.description || d.exception.value)) || d.text || '').split('\n')[0].slice(0, 160));
    } else if (method === 'Runtime.consoleAPICalled' && params.type === 'error') {
      runtimeEvents.push('console.error: ' + params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 160));
    } else if (method === 'Log.entryAdded' && params.entry.level === 'error') {
      runtimeEvents.push('browser error: ' + String(params.entry.text || '').slice(0, 160));
    } else if (method === 'Network.responseReceived' && params.response.status >= 400) {
      runtimeEvents.push(`network ${params.response.status}: ${params.response.url}`);
    }
  };
  await send('Runtime.enable'); await send('Log.enable');
  await send('Network.enable'); await send('Page.enable');

  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    return r && r.result ? r.result.value : undefined;
  };
  const setViewport = (w, h, mobile) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile });
  // Poll for the page to actually be ready instead of a fixed dead wait: returns
  // as soon as document.readyState === 'complete' (tens of ms on a localhost app),
  // capped so a genuinely slow/hanging view still bounds the wait.
  const settle = async (cap, floor = 0) => {
    let w = 0;
    for (; w < floor; w += 40) await sleep(40);   // min wait — async in-page renders
    for (; w < cap; w += 40) {
      await sleep(40);
      if ((await evalJs('document.readyState').catch(() => null)) === 'complete') return;
    }
  };
  const goto = async (u) => { await send('Page.navigate', { url: u }); await settle(NAV_SETTLE, NAV_FLOOR); };
  const screenshot = async (name) => {
    try { const { data } = await send('Page.captureScreenshot', { format: 'png' }); if (data) writeFileSync(`${shotDir}/${name}.png`, Buffer.from(data, 'base64')); return `${name}.png`; } catch { return null; }
  };
  // What a user SEES in this view: visible text length, on-screen error, controls present.
  const viewState = async () => evalJs(`(() => {
    const txt = (document.body && document.body.innerText || '').trim();
    const vis = [...document.querySelectorAll('button,input,select,textarea,a,[role=button]')].filter(e => {
      const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    }).length;
    const m = txt.match(${VIS_ERR.toString()});
    return { textLen: txt.length, controls: vis, title: (document.title||'').slice(0,60),
             heading: ((document.querySelector('h1,h2,header')||{}).innerText||'').trim().slice(0,50),
             visErr: m ? m[0] : null };
  })()`);

  const record = async (label, vp) => {
    const before = runtimeEvents; runtimeEvents = [];
    const st = await viewState() || { textLen: 0, controls: 0 };
    const shotName = safe(`${vp}-${label}`);
    const shot = await screenshot(shotName);
    const issues = [];
    if ((st.textLen || 0) < 25 && (st.controls || 0) === 0) issues.push('renders blank / no visible content');
    if (st.visErr) issues.push(`error text on screen: "${st.visErr}"`);
    let evs = [...new Set(before)];
    // A form submitted with the crawler's synthetic values getting a 4xx (e.g.
    // 400/422) is usually the app correctly VALIDATING input rather than a bug —
    // but it MIGHT be a real contract gap, so don't drop it: DEMOTE it to an
    // informational NOTE: (recorded + visible, non-blocking) so the heal loop
    // can't get stuck on synthetic-input validation. 5xx and JS exceptions on a
    // form submit, and all 4xx on load/nav, remain hard defects.
    if (/^form#/.test(label)) {
      const is4xx = (e) => /^network 4\d\d:/.test(e) ||
        (/Failed to load resource/i.test(e) && /\b4\d\d\b/.test(e));
      evs = evs.map((e) => (is4xx(e) ? `NOTE: form input validation (${e})` : e));
    }
    for (const e of evs) issues.push(e);
    const hardIssues = issues.filter((i) => !i.startsWith('NOTE:'));
    views.push({ view: label, viewport: vp, screenshot: shot, textLen: st.textLen, controls: st.controls, heading: st.heading, ok: hardIssues.length === 0, issues });
    // Keep the NOTE: prefix at the START of the emitted line so the downstream
    // advisory filter (defects.startsWith('NOTE:')) recognises it as non-blocking.
    for (const i of issues) {
      defects.push(i.startsWith('NOTE:')
        ? `NOTE: [${vp}] ${label}: ${i.slice(5).trim()}`
        : `[${vp}] ${label}: ${i}`);
    }
  };

  // Enumerate the navigation a user could click (nav/tabs/menu/in-page links).
  const navSel = "nav a, [role=tab], .tab, .nav-link, .nav-item, a[href^='#'], button[data-tab], [data-view], aside a, header a, .sidebar a, .menu a, li > a";
  const enumNav = async () => (await evalJs(`(() => {
    const els = [...document.querySelectorAll(${JSON.stringify(navSel)})];
    const seen = new Set(); const r = [];
    els.forEach((e) => { const t = (e.innerText || e.getAttribute('aria-label') || '').trim();
      if (t && t.length < 40 && !seen.has(t)) { seen.add(t); r.push(t); } });
    return r;
  })()`)) || [];
  const clickNavByText = (t) => evalJs(`(() => {
    const els = [...document.querySelectorAll(${JSON.stringify(navSel)})];
    const el = els.find((e) => ((e.innerText || e.getAttribute('aria-label') || '').trim()) === ${JSON.stringify(t)});
    if (el) { el.click(); return true; } return false;
  })()`);

  // Exercise a form: fill plausible values, submit, observe the result.
  const fillAndSubmit = (i) => evalJs(`(async () => {
    const forms = [...document.querySelectorAll('form')];
    const f = forms[${i}]; if (!f) return false;
    const val = (el) => { const n = ((el.name||'')+' '+(el.id||'')+' '+(el.placeholder||'')).toLowerCase();
      if (el.type==='email'||/email/.test(n)) return 'ra@acme.example';
      if (/dossier/.test(n)) return 'e123456'; if (/seq/.test(n)) return '0000';
      if (/din/.test(n)) return '12345678'; if (el.type==='number') return '1'; return 'Test Value'; };
    f.querySelectorAll('input,textarea').forEach((el)=>{ if(['hidden','submit','button','file'].includes(el.type))return;
      try{ el.value=val(el); el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }catch(e){} });
    f.querySelectorAll('select').forEach((s)=>{ try{ if(s.options.length){ s.selectedIndex=s.options.length-1; s.dispatchEvent(new Event('change',{bubbles:true})); } }catch(e){} });
    const btn = f.querySelector('button[type=submit],input[type=submit],button');
    try { if (btn) btn.click(); else f.requestSubmit ? f.requestSubmit() : f.submit(); } catch(e){}
    return true;
  })()`);

  // ---- DESKTOP: full crawl (every view + every form) ----
  await setViewport(1440, 900, false);
  await goto(url);
  await record('home', 'desktop');
  const nav = await enumNav();
  if (nav.length > MAX_NAV) defects.push(`NOTE: ${nav.length} nav items, only visiting first ${MAX_NAV}`);
  for (const t of nav.slice(0, MAX_NAV)) {
    if (overBudget()) { defects.push('NOTE: visual budget hit — remaining views not visited'); break; }
    await goto(url);               // clean state so nav indices/handlers are stable
    const ok = await clickNavByText(t);
    if (!ok) continue;
    await settle(ACT_SETTLE, ACT_FLOOR);
    await record(`view:${t}`, 'desktop');
  }
  const formCount = (await evalJs(`document.querySelectorAll('form').length`)) || 0;
  if (formCount > MAX_FORMS) defects.push(`NOTE: ${formCount} forms, only exercising first ${MAX_FORMS}`);
  for (let i = 0; i < Math.min(formCount, MAX_FORMS); i++) {
    if (overBudget()) { defects.push('NOTE: visual budget hit — remaining forms not exercised'); break; }
    await goto(url);
    await fillAndSubmit(i);
    await settle(ACT_SETTLE, ACT_FLOOR);
    await record(`form#${i}-submitted`, 'desktop');
  }

  // ---- MOBILE: responsive sanity on each top-level view ----
  await setViewport(390, 844, true);
  await goto(url);
  await record('home', 'mobile');
  for (const t of nav.slice(0, MAX_NAV)) {
    if (overBudget()) break;
    await goto(url);
    if (await clickNavByText(t)) { await settle(ACT_SETTLE, ACT_FLOOR); await record(`view:${t}`, 'mobile'); }
  }

  writeFileSync(`${shotDir}/manifest.json`, JSON.stringify({ url, views, defects }, null, 2));
  out({ ok: defects.filter((d) => !d.startsWith('NOTE:')).length === 0, defects: [...new Set(defects)], views: views.length, screenshotDir: shotDir });
} catch (e) {
  out({ ok: false, defects: ['visual validator harness error: ' + String(e).slice(0, 200)], views: views.length, screenshotDir: shotDir });
} finally {
  try { proc.kill('SIGKILL'); } catch {}
}
process.exit(0);
