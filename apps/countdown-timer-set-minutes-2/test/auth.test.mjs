import { describe, it, expect } from 'vitest'
import {
  hashPassword,
  verifyPassword,
  signToken,
  verifyToken,
} from '../server/auth.mjs'

// Ships in every ADF app: its auth primitives are tested on every build.
describe('auth', () => {
  it('hashes a password (never plaintext) and verifies it', () => {
    const h = hashPassword('hunter2')
    expect(h).not.toContain('hunter2')
    expect(h.startsWith('scrypt$')).toBe(true)
    expect(verifyPassword('hunter2', h)).toBe(true)
    expect(verifyPassword('wrong', h)).toBe(false)
  })

  it('uses a fresh salt per hash', () => {
    expect(hashPassword('x')).not.toBe(hashPassword('x'))
  })

  it('signs and verifies a session token, rejecting tampering', () => {
    const t = signToken({ uid: 7 })
    expect(verifyToken(t)).toEqual({ uid: 7 })
    expect(verifyToken(t.slice(0, -1) + (t.slice(-1) === 'a' ? 'b' : 'a'))).toBeNull()
    expect(verifyToken('not.a.token')).toBeNull()
  })
})
