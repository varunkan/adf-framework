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

describe('tip-calculator API', () => {
  it('computes tip, total, and per-person split (REQ-001, REQ-002)', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip',
      payload: { bill: 100, tipPercent: 20, people: 4 },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.tipAmount).toBe(20);
    expect(body.total).toBe(120);
    expect(body.perPerson).toBe(30);
    expect(body.id).toBeGreaterThan(0);
  });

  it('handles single person split', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip',
      payload: { bill: 50, tipPercent: 10, people: 1 },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.tipAmount).toBe(5);
    expect(body.total).toBe(55);
    expect(body.perPerson).toBe(55);
  });

  it('rejects a non-positive bill with 400', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip',
      payload: { bill: 0, tipPercent: 15, people: 2 },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBeTruthy();
  });

  it('rejects fewer than one person with 400', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip',
      payload: { bill: 40, tipPercent: 15, people: 0 },
    });
    expect(res.statusCode).toBe(400);
  });

  it('rejects negative tip percent with 400', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/tip',
      payload: { bill: 40, tipPercent: -5, people: 2 },
    });
    expect(res.statusCode).toBe(400);
  });

  it('lists calculations and fetches one by id', async () => {
    const created = await app.inject({
      method: 'POST',
      url: '/api/tip',
      payload: { bill: 80, tipPercent: 25, people: 2 },
    });
    const id = created.json().id;

    const list = await app.inject({ method: 'GET', url: '/api/tip' });
    expect(list.statusCode).toBe(200);
    expect(Array.isArray(list.json())).toBe(true);

    const one = await app.inject({ method: 'GET', url: `/api/tip/${id}` });
    expect(one.statusCode).toBe(200);
    expect(one.json().id).toBe(id);
  });

  it('returns 404 for a missing calculation', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/tip/9999999' });
    expect(res.statusCode).toBe(404);
  });
});
