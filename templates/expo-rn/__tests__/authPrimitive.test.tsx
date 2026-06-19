// Regression guard for the SHIPPED auth primitive (src/auth.ts). Kept on scaffold
// (it tests a kept kit file, like kit/theme tests). expo-crypto is mocked with REAL
// node crypto so the test runs deterministically without the native module — it
// proves the primitive's LOGIC: CSPRNG-unique salts, real-hash round-trip, wrong
// password rejected, and the plaintext is never present in the stored value.
jest.mock('expo-crypto', () => {
  const nodeCrypto = require('crypto');
  return {
    CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
    getRandomBytesAsync: async (n: number) =>
      Uint8Array.from(nodeCrypto.randomBytes(n)),
    digestStringAsync: async (_algo: string, data: string) =>
      nodeCrypto.createHash('sha256').update(data).digest('hex'),
  };
});

import {
  hashPassword,
  verifyPassword,
  generateSalt,
  generateToken,
} from '../src/auth';

describe('auth primitive (real CSPRNG + SHA-256)', () => {
  it('stores salt:hash, never the plaintext, and round-trips', async () => {
    const pw = 'correct horse battery staple';
    const stored = await hashPassword(pw);
    expect(stored).toContain(':');
    expect(stored).not.toContain(pw);
    expect(await verifyPassword(pw, stored)).toBe(true);
    expect(await verifyPassword('wrong password', stored)).toBe(false);
  });

  it('uses a unique CSPRNG salt per hash (same password -> different stored)', async () => {
    const a = await hashPassword('same');
    const b = await hashPassword('same');
    expect(a).not.toBe(b);
  });

  it('generateSalt / generateToken are hex and unique', async () => {
    expect(await generateSalt()).toMatch(/^[0-9a-f]+$/);
    expect(await generateToken()).toMatch(/^[0-9a-f]{64}$/);
    expect(await generateToken()).not.toBe(await generateToken());
  });
});
