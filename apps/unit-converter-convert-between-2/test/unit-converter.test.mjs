import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { buildApp } from '../server/app.mjs';

let app;

beforeAll(async () => {
  app = await buildApp();
  await app.ready();
});

afterAll(async () => {
  await app.close();
});

describe('unit-converter API', () => {
  it('converts meters to feet (REQ-001)', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/convert',
      payload: { direction: 'm-to-ft', value: 1 },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.direction).toBe('m-to-ft');
    expect(body.input).toBe(1);
    expect(body.output).toBeCloseTo(3.28084, 4);
  });

  it('converts feet to meters (REQ-002)', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/convert',
      payload: { direction: 'ft-to-m', value: 3.28084 },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.direction).toBe('ft-to-m');
    expect(body.output).toBeCloseTo(1, 4);
  });

  it('rejects invalid direction with 400', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/convert',
      payload: { direction: 'km-to-mi', value: 5 },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBeTruthy();
  });

  it('rejects non-numeric value with 400', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/convert',
      payload: { direction: 'm-to-ft', value: 'abc' },
    });
    expect(res.statusCode).toBe(400);
  });

  it('lists conversion history', async () => {
    await app.inject({
      method: 'POST',
      url: '/api/convert',
      payload: { direction: 'm-to-ft', value: 10 },
    });
    const res = await app.inject({ method: 'GET', url: '/api/conversions' });
    expect(res.statusCode).toBe(200);
    const rows = res.json();
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBeGreaterThan(0);
  });
});
