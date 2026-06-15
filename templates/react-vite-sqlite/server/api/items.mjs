import { db } from '../db.mjs'

export default async function items(app) {
  app.get('/items', async () => db.prepare('SELECT id, title FROM items ORDER BY id DESC').all())

  app.post('/items', async (req, reply) => {
    const { title } = req.body || {}
    if (!title || typeof title !== 'string') {
      return reply.code(400).send({ error: 'title is required' })
    }
    const info = db.prepare('INSERT INTO items (title) VALUES (?)').run(title)
    return reply.code(201).send({ id: Number(info.lastInsertRowid), title })
  })

  app.delete('/items/:id', async (req, reply) => {
    const info = db.prepare('DELETE FROM items WHERE id = ?').run(req.params.id)
    if (info.changes === 0) return reply.code(404).send({ error: 'not found' })
    return { deleted: Number(req.params.id) }
  })
}
