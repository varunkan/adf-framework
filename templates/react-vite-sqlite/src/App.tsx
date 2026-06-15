import { useEffect, useState } from 'react'

type Item = { id: number; title: string }

export default function App() {
  const [items, setItems] = useState<Item[]>([])
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(true)

  async function load() {
    const res = await fetch('/api/items')
    setItems(await res.json())
    setLoading(false)
  }
  useEffect(() => {
    load()
  }, [])

  async function add(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    await fetch('/api/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title.trim() }),
    })
    setTitle('')
    load()
  }
  async function remove(id: number) {
    await fetch(`/api/items/${id}`, { method: 'DELETE' })
    load()
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <div className="mx-auto max-w-xl px-6 py-10">
        <h1 className="mb-6 text-center text-3xl font-bold text-indigo-600">ADF · Starter</h1>
        <form onSubmit={add} className="mb-6 flex gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Add an item…"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500"
          />
          <button className="rounded-lg bg-indigo-600 px-4 py-2 font-semibold text-white hover:bg-indigo-700">
            Add
          </button>
        </form>
        {loading ? (
          <p className="text-center text-slate-400">Loading…</p>
        ) : (
          <ul className="space-y-2">
            {items.map((it) => (
              <li
                key={it.id}
                className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-3"
              >
                <span>{it.title}</span>
                <button onClick={() => remove(it.id)} className="text-sm text-slate-400 hover:text-red-500">
                  delete
                </button>
              </li>
            ))}
            {items.length === 0 && <li className="text-center text-slate-400">No items yet.</li>}
          </ul>
        )}
      </div>
    </div>
  )
}
