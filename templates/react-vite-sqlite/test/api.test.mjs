import { describe, it, expect, beforeEach } from 'vitest'
import { buildApp } from '../server/app.mjs'
import { db } from '../server/db.mjs'

describe('items API', () => {
  beforeEach(() => {
    db.exec('DELETE FROM items')
  })

  it('creates then lists an item', async () => {
    const app = await buildApp()
    const created = await app.inject({ method: 'POST', url: '/api/items', payload: { title: 'hello' } })
    expect(created.statusCode).toBe(201)
    expect(created.json().title).toBe('hello')

    const list = await app.inject({ method: 'GET', url: '/api/items' })
    expect(list.statusCode).toBe(200)
    expect(list.json()).toHaveLength(1)
    await app.close()
  })

  it('rejects an empty title with 400', async () => {
    const app = await buildApp()
    const res = await app.inject({ method: 'POST', url: '/api/items', payload: {} })
    expect(res.statusCode).toBe(400)
    await app.close()
  })

  it('404 on deleting a missing item', async () => {
    const app = await buildApp()
    const res = await app.inject({ method: 'DELETE', url: '/api/items/9999' })
    expect(res.statusCode).toBe(404)
    await app.close()
  })
})
