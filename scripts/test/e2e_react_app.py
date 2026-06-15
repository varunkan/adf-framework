#!/usr/bin/env python3
"""End-to-end gate for DAG nodes N9 (e2e-build) and N10 (e2e-edit) — the
FOUNDATION milestone's definition of done, scripted and deterministic.

The model is STUBBED (no network) but EVERYTHING else is real: the runner's
scaffold-then-diff generate flow, npm ci + `tsc && vite build` + vitest, and the
app booted EXACTLY as AppRunner boots it (`node server/index.mjs` on PORT). We
then drive it over HTTP like the dashboard iframe does.

N9 — one prompt builds a real React+Vite+Tailwind+SQLite app that:
     * boots and serves the built SPA at GET /  (200, references the vite bundle),
     * round-trips its JSON API with SQLite persistence (POST then GET).
N10 — a one-box edit applies the SMALLEST multi-file change, the app rebuilds and
     re-serves with the change live (proving the Lovable edit loop on a real app).

    python3 scripts/test/e2e_react_app.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REAL_TPL = os.path.join(ROOT, "templates", "react-vite-sqlite")

os.environ["ADF_STACK"] = "react-vite-sqlite"
os.environ["ADF_HEADROOM"] = "0"
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))
import agent_runner as ar  # noqa: E402

FID = "notes"

BUILD_OUTPUT = """\
<<<FILE: schema.sql>>>
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
<<<END>>>
<<<FILE: server/api/notes.mjs>>>
import { db } from '../db.mjs'

export default async function notes(app) {
  app.get('/notes', async () => db.prepare('SELECT id, body FROM notes ORDER BY id DESC').all())

  app.post('/notes', async (req, reply) => {
    const { body } = req.body || {}
    if (!body || typeof body !== 'string') {
      return reply.code(400).send({ error: 'body is required' })
    }
    const info = db.prepare('INSERT INTO notes (body) VALUES (?)').run(body)
    return reply.code(201).send({ id: Number(info.lastInsertRowid), body })
  })

  app.delete('/notes/:id', async (req, reply) => {
    const info = db.prepare('DELETE FROM notes WHERE id = ?').run(req.params.id)
    if (info.changes === 0) return reply.code(404).send({ error: 'not found' })
    return { deleted: Number(req.params.id) }
  })
}
<<<END>>>
<<<FILE: src/App.tsx>>>
import { useEffect, useState } from 'react'

type Note = { id: number; body: string }

export default function App() {
  const [notes, setNotes] = useState<Note[]>([])
  const [body, setBody] = useState('')

  async function load() {
    const res = await fetch('/api/notes')
    setNotes(await res.json())
  }
  useEffect(() => {
    load()
  }, [])

  async function add(e: React.FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    await fetch('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body: body.trim() }),
    })
    setBody('')
    load()
  }

  return (
    <div className="min-h-screen bg-slate-50 p-8 text-slate-800">
      <h1 className="text-2xl font-bold text-indigo-600">Notes</h1>
      <form onSubmit={add} className="my-4 flex gap-2">
        <input value={body} onChange={(e) => setBody(e.target.value)} className="flex-1 rounded border px-2 py-1" />
        <button className="rounded bg-indigo-600 px-3 py-1 font-semibold text-white">Add</button>
      </form>
      <ul className="space-y-1">
        {notes.map((n) => (
          <li key={n.id} className="rounded bg-white px-3 py-2">{n.body}</li>
        ))}
      </ul>
    </div>
  )
}
<<<END>>>
<<<FILE: test/notes.test.mjs>>>
import { describe, it, expect, beforeEach } from 'vitest'
import { buildApp } from '../server/app.mjs'
import { db } from '../server/db.mjs'

describe('notes API', () => {
  beforeEach(() => { db.exec('DELETE FROM notes') })
  it('creates then lists a note', async () => {
    const app = await buildApp()
    const c = await app.inject({ method: 'POST', url: '/api/notes', payload: { body: 'hi' } })
    expect(c.statusCode).toBe(201)
    const list = await app.inject({ method: 'GET', url: '/api/notes' })
    expect(list.json()).toHaveLength(1)
    await app.close()
  })
  it('rejects an empty body with 400', async () => {
    const app = await buildApp()
    const res = await app.inject({ method: 'POST', url: '/api/notes', payload: {} })
    expect(res.statusCode).toBe(400)
    await app.close()
  })
})
<<<END>>>
"""

# The one-box edit: rename the heading. Smallest multi-file diff (only App.tsx).
EDIT_OUTPUT = BUILD_OUTPUT[BUILD_OUTPUT.index("<<<FILE: src/App.tsx>>>"):BUILD_OUTPUT.index("<<<FILE: test/notes.test.mjs>>>")].replace(
    ">Notes</h1>", ">My Notes</h1>"
)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url, timeout=2):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def _post(url, payload, timeout=2):
    import json
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")


class Boot:
    """Boot the app EXACTLY as AppRunner does: `node server/index.mjs` on PORT."""
    def __init__(self, app_dir):
        self.app_dir = app_dir
        self.port = _free_port()
        self.proc = None

    def __enter__(self):
        self.proc = subprocess.Popen(
            ["node", "server/index.mjs"], cwd=self.app_dir,
            env=dict(os.environ, PORT=str(self.port)),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited:\n{self.proc.stdout.read()[-1000:]}")
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return self
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("server did not listen within 20s")

    def __exit__(self, *a):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"


def run_main(workspace, prompt):
    sys.argv = ["agent_runner.py", prompt, "--workspace", workspace]
    try:
        ar.main()
    except SystemExit as e:
        return e.code or 0
    return 0


def main():
    if not os.path.isdir(REAL_TPL):
        print(f"GATE FAIL: template missing: {REAL_TPL}", file=sys.stderr)
        return 1
    tmp = tempfile.mkdtemp(prefix="adf-e2e-")
    os.environ["ORCH_REPO_ROOT"] = tmp
    shutil.copytree(
        REAL_TPL, os.path.join(tmp, "templates", "react-vite-sqlite"),
        ignore=shutil.ignore_patterns("node_modules", "dist", "*.db", ".adf-deps"))
    spec_dir = os.path.join(tmp, "specs", FID)
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "spec.md"), "w") as f:
        f.write("# Notes\nAdd, list, delete short notes persisted in SQLite. "
                "Empty notes are rejected (400).\n")
    app_dir = os.path.join(tmp, "apps", FID)
    checks = {}

    try:
        # ---- N9: one prompt -> a real app that builds, boots, serves, persists --
        ar.generate = lambda m, t: (BUILD_OUTPUT, {})
        checks["N9 runner build verified (exit 0)"] = (
            run_main(tmp, f"resume {FID}") == 0)
        checks["N9 .adf-stack.json present (AppRunner contract)"] = os.path.isfile(
            os.path.join(app_dir, ".adf-stack.json"))

        with Boot(app_dir) as b:
            code, html = _get(b.url("/"))
            checks["N9 GET / serves the SPA (200)"] = code == 200
            checks["N9 / references the built vite bundle"] = (
                'id="root"' in html and "/assets/" in html)
            pc, _ = _post(b.url("/api/notes"), {"body": "from-e2e"})
            checks["N9 POST /api/notes persists (201)"] = pc == 201
            gc, body = _get(b.url("/api/notes"))
            checks["N9 GET /api/notes returns the persisted note"] = (
                gc == 200 and "from-e2e" in body)
            bad, _ = _post(b.url("/api/notes"), {})
            checks["N9 empty note rejected (400)"] = bad == 400

        # ---- N10: one-box edit -> smallest multi-file change, rebuilt + re-served -
        with open(os.path.join(app_dir, ar.EDIT_REQUEST_FILE), "w") as f:
            f.write("rename the heading to 'My Notes'")
        ar.generate = lambda m, t: (EDIT_OUTPUT, {})
        checks["N10 one-box edit re-verified (exit 0)"] = (
            run_main(tmp, f"resume {FID}") == 0)
        app_src = open(os.path.join(app_dir, "src", "App.tsx")).read()
        checks["N10 edit applied to src/App.tsx"] = "My Notes" in app_src
        checks["N10 edit request consumed"] = not os.path.isfile(
            os.path.join(app_dir, ar.EDIT_REQUEST_FILE))

        with Boot(app_dir) as b:
            code, _ = _get(b.url("/"))
            checks["N10 edited app still boots + serves (200)"] = code == 200
            # The built bundle now contains the new heading text.
            dist = os.path.join(app_dir, "dist", "assets")
            js = ""
            if os.path.isdir(dist):
                for fn in os.listdir(dist):
                    if fn.endswith(".js"):
                        js += open(os.path.join(dist, fn), encoding="utf-8", errors="ignore").read()
            checks["N10 'My Notes' compiled into the live bundle"] = "My Notes" in js
    finally:
        ok = all(checks.values())
        for name, passed in checks.items():
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        shutil.rmtree(tmp, ignore_errors=True)

    print("GATE PASS: prompt -> real React+Vite+SQLite app builds, boots, serves, "
          "persists, and hot-edits (FOUNDATION milestone met)"
          if ok else "GATE FAIL: e2e did not meet the foundation definition of done")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
