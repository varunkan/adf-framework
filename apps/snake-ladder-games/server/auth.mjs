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
// JWT dependency. Set ADF_AUTH_SECRET in production; the dev default is obvious.
const SECRET = process.env.ADF_AUTH_SECRET || 'adf-dev-secret-set-ADF_AUTH_SECRET'

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
