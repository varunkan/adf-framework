#!/usr/bin/env python3
"""System gate for DAG node N7 (runner-generate, scaffold-then-diff): drive the
REAL agent_runner.main() generate flow end-to-end with the model STUBBED (no
network, deterministic). Proves the pipeline — resolve react stack -> scaffold the
checked-in template -> write the feature's <<<FILE:>>> diffs -> verify_app(react)
(npm ci -> tsc+vite build -> vitest -> node boot) — produces a real, buildable,
booting app. Exit 0 only if main() reports the feature verified.

    python3 scripts/test/runner_generate_check.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REAL_TPL = os.path.join(ROOT, "templates", "react-vite-sqlite")

# DEFAULT_STACK is read at import time — select react BEFORE importing the runner.
os.environ["ADF_STACK"] = "react-vite-sqlite"
os.environ["ADF_HEADROOM"] = "0"  # no headroom needed for a stubbed model
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))
import agent_runner as ar  # noqa: E402

FID = "genfeature"

# A canonical, type-correct "notes" feature the stubbed model "returns". It mirrors
# the template's proven items feature (renamed), so a green gate isolates the
# scaffold->write->verify wiring rather than the model's code quality.
CANNED = """\
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
        <input
          value={body}
          onChange={(e) => setBody(e.target.value)}
          className="flex-1 rounded border px-2 py-1"
          placeholder="Write a note…"
        />
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
  beforeEach(() => {
    db.exec('DELETE FROM notes')
  })

  it('creates then lists a note', async () => {
    const app = await buildApp()
    const created = await app.inject({ method: 'POST', url: '/api/notes', payload: { body: 'hi' } })
    expect(created.statusCode).toBe(201)
    const list = await app.inject({ method: 'GET', url: '/api/notes' })
    expect(list.statusCode).toBe(200)
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


def main():
    if not os.path.isdir(REAL_TPL):
        print(f"GATE FAIL: template missing: {REAL_TPL}", file=sys.stderr)
        return 1

    tmp = tempfile.mkdtemp(prefix="adf-gen-")
    # An isolated "repo": the template (so scaffold finds it) + a spec for the feature.
    shutil.copytree(
        REAL_TPL, os.path.join(tmp, "templates", "react-vite-sqlite"),
        ignore=shutil.ignore_patterns("node_modules", "dist", "*.db", ".adf-deps"),
    )
    spec_dir = os.path.join(tmp, "specs", FID)
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "spec.md"), "w") as f:
        f.write("# Notes\nUsers can add, list, and delete short text notes that "
                "persist in SQLite. Empty notes are rejected (400).\n")

    # Stub the model: main() will scaffold + write these files + really verify them.
    ar.generate = lambda messages, timeout: (CANNED, {"prompt_tokens": 0, "completion_tokens": 0})

    os.environ["ORCH_REPO_ROOT"] = tmp
    sys.argv = ["agent_runner.py", f"resume {FID}", "--workspace", tmp]

    code = 0
    try:
        ar.main()
    except SystemExit as e:
        code = e.code or 0

    app_dir = os.path.join(tmp, "apps", FID)
    have = lambda rel: os.path.isfile(os.path.join(app_dir, rel))
    checks = {
        "main() exit 0 (verified)": code == 0,
        "scaffold package.json": have("package.json"),
        "scaffold server/app.mjs (not re-emitted)": have("server/app.mjs"),
        "generated server/api/notes.mjs": have("server/api/notes.mjs"),
        "generated src/App.tsx": have("src/App.tsx"),
        "generated test/notes.test.mjs": have("test/notes.test.mjs"),
        "sample items.mjs stripped": not have("server/api/items.mjs"),
        ".adf-stack.json present (AppRunner contract)": have(".adf-stack.json"),
    }
    ok = all(checks.values())
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("GATE PASS: scaffold-then-diff generated a real, verified react app"
          if ok else "GATE FAIL: generate flow did not produce a verified app")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
