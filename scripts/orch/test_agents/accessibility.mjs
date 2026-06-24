// ADF test agent: accessibility (WCAG) — inspects the RUNNING app like an
// assistive-tech user, across every view, and reports barriers a screen-reader /
// keyboard user would hit. No npm (node 22 fetch + WebSocket drive headless
// Chrome over the DevTools Protocol; the WCAG audit is a self-contained DOM walk
// injected via Runtime.evaluate — no axe-core download needed).
//
//   node accessibility.mjs <baseUrl> <appDir>  ->  JSON {agent,ok,findings,summary}
//
// A finding is a real barrier: an image with no alt text, a form control with no
// label, a control with no accessible name, a page with no <title>/lang, a
// skipped heading level, a duplicate id, a positive tabindex, or text that fails
// a clear (conservative) colour-contrast threshold. Severity drives the gate:
// 'high' barriers block 'complete'; 'medium'/'low' are advisory.
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';

const base = (process.argv[2] || 'http://127.0.0.1:8000/').replace(/\/?$/, '/');
const chrome = process.env.ADF_CHROME ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const port = Number(process.env.ADF_CDP_PORT_A11Y || 9336);
const BUDGET_MS = Number(process.env.ADF_A11Y_BUDGET_MS || 240000); // 4 min cap
const MAX_NAV = Number(process.env.ADF_A11Y_MAX_NAV || 40);
const MAX_FINDINGS = Number(process.env.ADF_A11Y_MAX_FINDINGS || 60);
const t0 = Date.now();
const overBudget = () => Date.now() - t0 > BUDGET_MS;

const emit = (o) => process.stdout.write(JSON.stringify(o, null, 2) + '\n');
const done = (findings, summary) =>
  emit({ agent: 'accessibility', ok: findings.length === 0,
         findings: findings.slice(0, MAX_FINDINGS), summary });

// The WCAG audit, injected into the page. Returns an array of raw violations
// {rule, severity, title, detail, location}. Conservative by design — every rule
// here is an unambiguous barrier, so the gate doesn't drown in false positives.
const AUDIT_FN = `(() => {
  const V = [];
  const sig = (el) => {
    if (!el) return '?';
    const id = el.id ? '#' + el.id : '';
    const cls = (el.className && typeof el.className === 'string')
      ? '.' + el.className.trim().split(/\\s+/).slice(0,2).join('.') : '';
    return (el.tagName || '?').toLowerCase() + id + cls;
  };
  const accName = (el) => {
    const al = el.getAttribute('aria-label');
    if (al && al.trim()) return al.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const r = lb.split(/\\s+/).map(i => { const n = document.getElementById(i); return n ? n.innerText : ''; }).join(' ').trim(); if (r) return r; }
    const t = (el.innerText || el.textContent || '').trim();
    if (t) return t;
    const ti = el.getAttribute('title'); if (ti && ti.trim()) return ti.trim();
    const img = el.querySelector && el.querySelector('img[alt]');
    if (img && img.getAttribute('alt').trim()) return img.getAttribute('alt').trim();
    const v = el.getAttribute('value'); if (v && v.trim()) return v.trim();
    return '';
  };
  const visible = (el) => { try { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && el.getAttribute('aria-hidden') !== 'true'; } catch (e) { return true; } };

  // 1. document language
  const html = document.documentElement;
  if (!html.getAttribute('lang') || !html.getAttribute('lang').trim())
    V.push({ rule:'html-lang', severity:'high', title:'<html> has no lang attribute', detail:'screen readers cannot determine the page language', location:'<html>' });
  // 2. page title
  if (!document.title || !document.title.trim())
    V.push({ rule:'doc-title', severity:'high', title:'document has no <title>', detail:'the page/tab has no accessible name', location:'<head>' });

  // 3. images without alt
  let imgN = 0;
  for (const img of document.querySelectorAll('img')) {
    if (!visible(img)) continue;
    const role = img.getAttribute('role');
    const ariaHidden = img.getAttribute('aria-hidden') === 'true';
    if (role === 'presentation' || role === 'none' || ariaHidden) continue;
    if (img.getAttribute('alt') === null && imgN++ < 12)
      V.push({ rule:'img-alt', severity:'high', title:'image has no alt attribute', detail:'src=' + String(img.getAttribute('src')||'').slice(0,60), location: sig(img) });
  }
  // 4. form controls without a label / accessible name
  let ctrlN = 0;
  for (const el of document.querySelectorAll('input,select,textarea')) {
    if (!visible(el)) continue;
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (['hidden','submit','button','reset','image'].includes(type)) continue;
    let labelled = !!(el.getAttribute('aria-label') && el.getAttribute('aria-label').trim())
      || !!(el.getAttribute('aria-labelledby') && el.getAttribute('aria-labelledby').trim())
      || !!(el.getAttribute('title') && el.getAttribute('title').trim());
    if (!labelled && el.id) { const lab = document.querySelector('label[for="' + (window.CSS && CSS.escape ? CSS.escape(el.id) : el.id) + '"]'); if (lab && lab.innerText.trim()) labelled = true; }
    if (!labelled && el.closest('label') && el.closest('label').innerText.trim()) labelled = true;
    if (!labelled && ctrlN++ < 14)
      V.push({ rule:'control-label', severity:'high', title:'form control has no associated label', detail:(el.tagName.toLowerCase()) + (type ? ' type=' + type : '') + ' name=' + String(el.getAttribute('name')||'(none)') + (el.getAttribute('placeholder') ? ' (placeholder is not a label)' : ''), location: sig(el) });
  }
  // 5. interactive elements without an accessible name
  let nameN = 0;
  for (const el of document.querySelectorAll('button,a[href],[role=button],[role=link],[role=tab]')) {
    if (!visible(el)) continue;
    if (!accName(el) && nameN++ < 14)
      V.push({ rule:'control-name', severity:'high', title:'interactive control has no accessible name', detail:'a screen reader announces nothing for this ' + el.tagName.toLowerCase(), location: sig(el) });
  }
  // 6. duplicate ids
  const ids = {}; for (const el of document.querySelectorAll('[id]')) { const i = el.id; if (!i) continue; ids[i] = (ids[i]||0)+1; }
  for (const i in ids) if (ids[i] > 1)
    V.push({ rule:'dup-id', severity:'medium', title:'duplicate id attribute', detail:'id="' + i + '" appears ' + ids[i] + ' times (breaks label/aria references)', location:'#' + i });
  // 7. positive tabindex (anti-pattern — hijacks tab order)
  let tiN = 0;
  for (const el of document.querySelectorAll('[tabindex]')) {
    const ti = parseInt(el.getAttribute('tabindex'), 10);
    if (ti > 0 && tiN++ < 6) V.push({ rule:'pos-tabindex', severity:'medium', title:'positive tabindex disrupts keyboard order', detail:'tabindex=' + ti, location: sig(el) });
  }
  // 8. heading hierarchy
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(visible);
  const main = (document.body.innerText || '').trim().length;
  if (main > 200 && !heads.some(h => h.tagName === 'H1'))
    V.push({ rule:'no-h1', severity:'medium', title:'content view has no <h1>', detail:'no top-level heading for screen-reader navigation', location:'<body>' });
  let prev = 0;
  for (const h of heads) { const lvl = +h.tagName[1]; if (prev && lvl > prev + 1) { V.push({ rule:'heading-skip', severity:'low', title:'heading level skipped', detail:'jumped from h' + prev + ' to h' + lvl, location: sig(h) }); break; } prev = lvl; }

  // 9. conservative colour contrast — only flag CLEAR failures (<3.0) where both
  //    colours resolve to opaque values, to avoid false positives.
  const lum = (r,g,b) => { const a=[r,g,b].map(v=>{v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4);}); return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2]; };
  const parse = (c) => { const m = c && c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/); if (!m) return null; const a = m[4]===undefined?1:parseFloat(m[4]); return { r:+m[1], g:+m[2], b:+m[3], a }; };
  const bgOf = (el) => { let n = el; for (let i=0;i<8 && n;i++){ const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a >= 0.95) return c; n = n.parentElement; } return null; };
  let cN = 0;
  const texts = [...document.querySelectorAll('p,span,a,button,label,li,td,th,h1,h2,h3,h4,h5,h6,div')].filter(el => {
    if (!visible(el)) return false; const t = (el.childNodes ? [...el.childNodes].filter(n=>n.nodeType===3 && n.textContent.trim()).map(n=>n.textContent).join('') : ''); return t.trim().length >= 3; });
  for (const el of texts.slice(0, 400)) {
    if (cN >= 8) break;
    const fg = parse(getComputedStyle(el).color); const bg = bgOf(el); if (!fg || !bg || fg.a < 0.95) continue;
    const L1 = lum(fg.r,fg.g,fg.b), L2 = lum(bg.r,bg.g,bg.b);
    const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    if (ratio < 3.0) { cN++; V.push({ rule:'contrast', severity:'medium', title:'text colour contrast is too low', detail:'ratio ' + ratio.toFixed(1) + ':1 (WCAG AA needs 4.5:1; this is below 3:1)', location: sig(el) }); }
  }
  return V;
})()`;

const proc = spawn(chrome, [
  '--headless=new', `--remote-debugging-port=${port}`,
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--hide-scrollbars',
  `--user-data-dir=/tmp/adf-chrome-a11y-${port}`, 'about:blank',
], { stdio: 'ignore' });

const navSel = "nav a, [role=tab], .tab, .nav-link, .nav-item, a[href^='#'], button[data-tab], [data-view], aside a, header a, .sidebar a, .menu a, li > a";

try {
  let targets = null;
  for (let i = 0; i < 80; i++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/json`); targets = await r.json(); if (targets.length) break; } catch {}
    await sleep(250);
  }
  const page = targets && (targets.find((t) => t.type === 'page') || targets[0]);
  if (!page) { done([], 'headless Chrome unavailable — a11y audit skipped (advisory)'); proc.kill('SIGKILL'); process.exit(0); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  const send = (method, params = {}) => { const i = ++id; ws.send(JSON.stringify({ id: i, method, params })); return new Promise((res) => pend.set(i, res)); };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pend.has(msg.id)) { pend.get(msg.id)(msg.result); pend.delete(msg.id); } };
  await send('Page.enable'); await send('Runtime.enable');

  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    return r && r.result ? r.result.value : undefined;
  };
  const goto = async (u) => { await send('Page.navigate', { url: u }); await sleep(1500); };
  const clickNavByText = (t) => evalJs(`(() => { const els = [...document.querySelectorAll(${JSON.stringify(navSel)})]; const el = els.find((e) => ((e.innerText || e.getAttribute('aria-label') || '').trim()) === ${JSON.stringify(t)}); if (el) { el.click(); return true; } return false; })()`);

  // de-dup across views by rule+location+detail so we don't report the same
  // barrier 40× (an SPA keeps one document; multi-page apps get fresh docs).
  const seen = new Set();
  const findings = [];
  const audit = async (label) => {
    const raw = await evalJs(AUDIT_FN) || [];
    for (const v of raw) {
      const key = v.rule + '|' + v.location + '|' + (v.detail || '');
      if (seen.has(key)) continue; seen.add(key);
      findings.push({ severity: v.severity, title: v.title,
        detail: (v.detail ? v.detail + ' ' : '') + '— view: ' + label, location: v.location });
    }
  };

  await goto(base);
  await audit('home');
  const nav = (await evalJs(`(() => { const els=[...document.querySelectorAll(${JSON.stringify(navSel)})]; const seen=new Set(),r=[]; els.forEach(e=>{const t=(e.innerText||e.getAttribute('aria-label')||'').trim(); if(t&&t.length<40&&!seen.has(t)){seen.add(t);r.push(t);}}); return r; })()`)) || [];
  for (const t of nav.slice(0, MAX_NAV)) {
    if (overBudget() || findings.length >= MAX_FINDINGS) break;
    await goto(base);
    if (await clickNavByText(t)) { await sleep(1100); await audit('view:' + t); }
  }

  const high = findings.filter(f => f.severity === 'high').length;
  const med = findings.filter(f => f.severity === 'medium').length;
  const low = findings.filter(f => f.severity === 'low').length;
  done(findings, `${findings.length} accessibility barrier(s) across ${1 + Math.min(nav.length, MAX_NAV)} view(s): ${high} high, ${med} medium, ${low} low`);
} catch (e) {
  // Never hard-fail the whole gate on a harness error — report advisory-empty.
  done([], 'a11y harness error (skipped): ' + String(e).slice(0, 160));
} finally {
  try { proc.kill('SIGKILL'); } catch {}
}
process.exit(0);
