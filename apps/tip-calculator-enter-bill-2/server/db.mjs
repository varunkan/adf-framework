import Database from 'better-sqlite3'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const dbPath = process.env.ADF_DB_PATH || join(root, 'data.db')

export const db = new Database(dbPath)
db.pragma('journal_mode = WAL')

const schema = join(root, 'schema.sql')
if (existsSync(schema)) db.exec(readFileSync(schema, 'utf8'))
