import Fastify from 'fastify'
import fastifyStatic from '@fastify/static'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { existsSync, readdirSync } from 'node:fs'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')

export async function buildApp() {
  const app = Fastify({ logger: false })

  app.get('/api/health', async () => ({ ok: true }))

  const apiDir = join(here, 'api')
  if (existsSync(apiDir)) {
    for (const f of readdirSync(apiDir).filter((n) => n.endsWith('.mjs'))) {
      const mod = await import(join(apiDir, f))
      if (mod.default) await app.register(mod.default, { prefix: '/api' })
    }
  }

  const dist = join(root, 'dist')
  if (existsSync(dist)) {
    await app.register(fastifyStatic, { root: dist, prefix: '/' })
    app.setNotFoundHandler((req, reply) => {
      if (req.raw.url && req.raw.url.startsWith('/api')) {
        return reply.code(404).send({ error: 'not found' })
      }
      return reply.sendFile('index.html')
    })
  }

  return app
}
