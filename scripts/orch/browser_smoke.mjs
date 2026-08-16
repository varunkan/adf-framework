// ADF browser smoke gate — the layer unit tests and HTTP checks cannot see.
//
// Loads the running app in HEADLESS CHROME via the DevTools Protocol and reports
// the client-side defects a user sees in the preview: uncaught JS exceptions,
// console.error output, browser log errors, and failed (>=400) network calls the
// page makes. No npm install — uses node 22's built-in fetch + WebSocket.
//
// Usage: node browser_smoke.mjs <url>   ->  prints JSON {ok, defects:[...]}
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';

const url = process.argv[2] || 'http://127.0.0.1:8000/';
const chrome = process.env.ADF_CHROME ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const port = Number(process.env.ADF_CDP_PORT || 9333);
const out = (o) => process.stdout.write(JSON.stringify(o, null, 2) + '\n');

const proc = spawn(chrome, [
  '--headless=new', `--remote-debugging-port=${port}`,
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', `--user-data-dir=/tmp/adf-chrome-smoke-${port}`,
  'about:blank',
], { stdio: 'ignore' });

const defects = [];
try {
  let targets = null;
  for (let i = 0; i < 80; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json`);
      targets = await r.json();
      if (targets.length) break;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  const page = targets && (targets.find((t) => t.type === 'page') || targets[0]);
  if (!page) { out({ ok: false, defects: ['headless Chrome did not expose a CDP page'] }); proc.kill('SIGKILL'); process.exit(0); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  const send = (method, params = {}) => {
    const i = ++id; ws.send(JSON.stringify({ id: i, method, params }));
    return new Promise((res) => pend.set(i, res));
  };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pend.has(msg.id)) { pend.get(msg.id)(msg.result); pend.delete(msg.id); return; }
    const { method, params } = msg;
    if (method === 'Runtime.exceptionThrown') {
      const d = params.exceptionDetails || {};
      const txt = (d.exception && (d.exception.description || d.exception.value)) || d.text || 'unknown';
      defects.push('JS exception: ' + String(txt).split('\n')[0].slice(0, 180));
    } else if (method === 'Runtime.consoleAPICalled' && params.type === 'error') {
      defects.push('console.error: ' + params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 180));
    } else if (method === 'Log.entryAdded' && params.entry.level === 'error') {
      defects.push('browser error: ' + String(params.entry.text || '').slice(0, 180));
    } else if (method === 'Network.responseReceived') {
      const s = params.response.status;
      if (s >= 400) defects.push(`network ${s}: ${params.response.url}`);
    }
  };
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Network.enable');
  await send('Page.enable');
  await send('Page.navigate', { url });
  await sleep(3500); // render + run JS + initial fetches

  // EXERCISE THE UI like a user: fill inputs with plausible values and click every
  // button so the real POST/fetch flows fire — that is where interaction defects
  // (the errors a user actually hits) surface, which a passive load never shows.
  try {
    await send('Runtime.evaluate', {
      awaitPromise: true,
      expression: `(async () => {
        const val = (el) => {
          const n = ((el.name||'') + ' ' + (el.id||'') + ' ' + (el.placeholder||'')).toLowerCase();
          if (el.type === 'email' || /email/.test(n)) return 'ra@acme.example';
          if (/dossier/.test(n)) return 'e123456';
          if (/seq/.test(n)) return '0000';
          if (/din/.test(n)) return '12345678';
          if (el.type === 'number') return '1';
          return 'test';
        };
        document.querySelectorAll('input, textarea').forEach((el) => {
          if (['hidden','submit','button','file'].includes(el.type)) return;
          try { el.value = val(el); el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true})); } catch (e) {}
        });
        document.querySelectorAll('select').forEach((s) => {
          try { if (s.options.length) { s.selectedIndex = s.options.length - 1;
                s.dispatchEvent(new Event('change', {bubbles:true})); } } catch (e) {}
        });
        const btns = [...document.querySelectorAll('button, [role=button], input[type=submit]')];
        for (const b of btns.slice(0, 60)) {
          try { b.click(); } catch (e) {}
          await new Promise((r) => setTimeout(r, 120));
        }
        return btns.length;
      })()`,
    });
  } catch (e) { /* evaluate failure is itself caught via exceptions */ }
  await sleep(4000); // let click-triggered fetches resolve and errors surface

  out({ ok: defects.length === 0, defects: [...new Set(defects)] });
} catch (e) {
  out({ ok: false, defects: ['browser smoke harness error: ' + String(e).slice(0, 200)] });
} finally {
  try { proc.kill('SIGKILL'); } catch { /* ignore */ }
}
process.exit(0);
