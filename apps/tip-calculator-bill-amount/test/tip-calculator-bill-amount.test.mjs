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

describe('tip-calculator-bill-amount', () => {
  it('REQ-001/REQ-002: calculates tip, total and per-person split', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip/calculate',
      payload: { bill_amount: 100, tip_percent: 20, people: 4 },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.tip_amount).toBe(20);
    expect(body.total_amount).toBe(120);
    expect(body.per_person).toBe(30);
  });

  it('handles fractional rounding to 2 decimals', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip/calculate',
      payload: { bill_amount: 50, tip_percent: 15, people: 3 },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.tip_amount).toBe(7.5);
    expect(body.total_amount).toBe(57.5);
    expect(body.per_person).toBe(19.17);
  });

  it('rejects invalid bill amount with 400', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip/calculate',
      payload: { bill_amount: -5, tip_percent: 10, people: 2 },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBeTruthy();
  });

  it('rejects non-integer people with 400', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip/calculate',
      payload: { bill_amount: 50, tip_percent: 10, people: 0 },
    });
    expect(res.statusCode).toBe(400);
  });

  it('persists and retrieves a calculation', async () => {
    const create = await app.inject({
      method: 'POST',
      url: '/api/tip/calculations',
      payload: { bill_amount: 80, tip_percent: 10, people: 2 },
    });
    expect(create.statusCode).toBe(201);
    const saved = create.json();
    expect(saved.id).toBeTypeOf('number');
    expect(saved.tip_amount).toBe(8);
    expect(saved.total_amount).toBe(88);
    expect(saved.per_person).toBe(44);

    const get = await app.inject({
      method: 'GET',
      url: `/api/tip/calculations/${saved.id}`,
    });
    expect(get.statusCode).toBe(200);
    expect(get.json().id).toBe(saved.id);
  });

  it('returns 404 for missing calculation', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/tip/calculations/999999',
    });
    expect(res.statusCode).toBe(404);
  });

  it('lists calculations', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/tip/calculations',
    });
    expect(res.statusCode).toBe(200);
    expect(Array.isArray(res.json())).toBe(true);
  });
});
