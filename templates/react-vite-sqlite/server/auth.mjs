// Built-in auth primitives — provably-correct and OFFLINE (node:crypto only, no
// dependency, no network). Passwords are scrypt-hashed with a per-user salt and
// compared in constant time; sessions are signed with HMAC. ADF's policy gate
// enforces that a `password` column is never stored in plaintext, so these are the
// safe defaults every generated app ships with.
//
// Wire it into a feature like:
//   import { hashPassword, verifyPassword, signToken, verifyToken } from './auth.mjs'
//   // signup:  db.prepare('INSERT INTO users (email, password) VALUES (?, ?)')
//   //            .run(email, hashPassword(plain))
//   // login:   const row = db.prepare('SELECT * FROM users WHERE email=?').get(email)
//   //          if (verifyPassword(plain, row.password)) token = signToken({ uid: row.id })
import { scryptSync, randomBytes, timingSafeEqual, createHmac } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const KEYLEN = 64

/** Hash a password with a fresh random salt. Returns `scrypt$<salt>$<hash>`. */
export function hashPassword(password) {
  const salt = randomBytes(16).toString('hex')
  const hash = scryptSync(String(password), salt, KEYLEN).toString('hex')
  return `scrypt$${salt}$${hash}`
}

/** Constant-time verify of a password against a stored `scrypt$salt$hash`. */
export function verifyPassword(password, stored) {
  const [scheme, salt, hash] = String(stored).split('$')
  if (scheme !== 'scrypt' || !salt || !hash) return false
  const expected = Buffer.from(hash, 'hex')
  const actual = scryptSync(String(password), salt, KEYLEN)
  return actual.length === expected.length && timingSafeEqual(actual, expected)
}

// Sessions: a compact HMAC-signed token (`<base64url body>.<base64url sig>`), no
// JWT dependency. The signing secret is resolved in priority order:
//   1. the ADF_AUTH_SECRET env var — set this in production / CI;
//   2. a per-app `.adf-auth-secret` file (random 32 bytes) that ADF writes at
//      scaffold time, next to the app root — every generated app gets its OWN
//      secret, so a token signed for one app can never be replayed against another;
//   3. a fail-LOUD ephemeral random secret (warns; sessions won't survive a restart).
// There is deliberately NO world-known constant fallback — a shared default secret
// would let anyone forge a valid session against every app that shipped it.
function _resolveSecret() {
  const fromEnv = (process.env.ADF_AUTH_SECRET || '').trim()
  if (fromEnv) return fromEnv
  try {
    const file = join(dirname(fileURLToPath(import.meta.url)), '..', '.adf-auth-secret')
    const fromFile = readFileSync(file, 'utf8').trim()
    if (fromFile) return fromFile
  } catch { /* app wasn't scaffolded with a secret file — fall through */ }
  console.warn(
    '[adf-auth] No ADF_AUTH_SECRET env var and no .adf-auth-secret file found; ' +
    'using an ephemeral random secret. Sessions will NOT survive a restart. Set ' +
    'ADF_AUTH_SECRET (or let ADF scaffold .adf-auth-secret) for stable sessions.')
  return randomBytes(32).toString('hex')
}

const SECRET = _resolveSecret()

function _b64url(buf) {
  return Buffer.from(buf).toString('base64url')
}

/** Sign a small JSON payload into a tamper-evident session token. */
export function signToken(payload) {
  const body = _b64url(JSON.stringify(payload))
  const sig = createHmac('sha256', SECRET).update(body).digest('base64url')
  return `${body}.${sig}`
}

/** Verify a token and return its payload, or null if missing/forged/garbled. */
export function verifyToken(token) {
  const [body, sig] = String(token).split('.')
  if (!body || !sig) return null
  const expected = createHmac('sha256', SECRET).update(body).digest('base64url')
  const a = Buffer.from(sig)
  const b = Buffer.from(expected)
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null
  try {
    return JSON.parse(Buffer.from(body, 'base64url').toString('utf8'))
  } catch {
    return null
  }
}
