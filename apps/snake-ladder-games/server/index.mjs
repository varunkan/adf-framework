import { buildApp } from './app.mjs'

const port = parseInt(process.env.PORT || '8000', 10)
const app = await buildApp()
app
  .listen({ port, host: '127.0.0.1' })
  .then(() => console.log(`ADF app ready on http://127.0.0.1:${port}`))
  .catch((err) => {
    console.error(err)
    process.exit(1)
  })
