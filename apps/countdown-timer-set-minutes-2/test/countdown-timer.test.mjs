import { describe, it, expect, beforeEach } from 'vitest';
import { buildApp } from '../server/app.mjs';
import { db } from '../server/db.mjs';

describe('countdown-timer presets API', () => {
  beforeEach(() => {
    db.prepare('DELETE FROM timer_presets').run();
  });

  it('REQ-001/002/003: creates a preset with valid minutes and seconds', async () => {
    const app = await buildApp();
    const res = await app.inject({
      method: 'POST',
      url: '/api/presets',
      payload: { name: 'Work', minutes: 25, seconds: 0 },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.name).toBe('Work');
    expect(body.minutes).toBe(25);
    expect(body.seconds).toBe(0);
    expect(body.id).toBeGreaterThan(0);
  });

  it('lists created presets', async () => {
    const app = await buildApp();
    await app.inject({
      method: 'POST',
      url: '/api/presets',
      payload: { name: 'Break', minutes: 5, seconds: 30 },
    });
    const res = await app.inject({ method: 'GET', url: '/api/presets' });
    expect(res.statusCode).toBe(200);
    const list = res.json();
    expect(Array.isArray(list)).toBe(true);
    expect(list.length).toBe(1);
    expect(list[0].name).toBe('Break');
  });

  it('fetches a single preset by id', async () => {
    const app = await buildApp();
    const created = await app.inject({
      method: 'POST',
      url: '/api/presets',
      payload: { name: 'Tea', minutes: 3, seconds: 0 },
    });
    const id = created.json().id;
    const res = await app.inject({ method: 'GET', url: `/api/presets/${id}` });
    expect(res.statusCode).toBe(200);
    expect(res.json().name).toBe('Tea');
  });

  it('rejects out-of-range seconds with 400', async () => {
    const app = await buildApp();
    const res = await app.inject({
      method: 'POST',
      url: '/api/presets',
      payload: { name: 'Bad', minutes: 10, seconds: 99 },
    });
    expect(res.statusCode).toBe(400);
  });

  it('rejects missing name with 400', async () => {
    const app = await buildApp();
    const res = await app.inject({
      method: 'POST',
      url: '/api/presets',
      payload: { name: '', minutes: 1, seconds: 0 },
    });
    expect(res.statusCode).toBe(400);
  });

  it('rejects zero duration with 400', async () => {
    const app = await buildApp();
    const res = await app.inject({
      method: 'POST',
      url: '/api/presets',
      payload: { name: 'Zero', minutes: 0, seconds: 0 },
    });
    expect(res.statusCode).toBe(400);
  });

  it('returns 404 for missing preset', async () => {
    const app = await buildApp();
    const res = await app.inject({ method: 'GET', url: '/api/presets/99999' });
    expect(res.statusCode).toBe(404);
  });

  it('deletes a preset and returns 404 on second delete', async () => {
    const app = await buildApp();
    const created = await app.inject({
      method: 'POST',
      url: '/api/presets',
      payload: { name: 'Temp', minutes: 1, seconds: 1 },
    });
    const id = created.json().id;
    const del = await app.inject({ method: 'DELETE', url: `/api/presets/${id}` });
    expect(del.statusCode).toBe(200);
    const del2 = await app.inject({ method: 'DELETE', url: `/api/presets/${id}` });
    expect(del2.statusCode).toBe(404);
  });
});
