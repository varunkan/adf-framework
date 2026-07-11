import { db } from '../db.mjs';

function validate(minutes, seconds) {
  if (
    !Number.isInteger(minutes) ||
    !Number.isInteger(seconds) ||
    minutes < 0 ||
    minutes > 59 ||
    seconds < 0 ||
    seconds > 59
  ) {
    return false;
  }
  return true;
}

export default async function countdownTimer(app) {
  app.get('/presets', async (_req, reply) => {
    const rows = db
      .prepare('SELECT id, name, minutes, seconds, created_at FROM timer_presets ORDER BY id DESC')
      .all();
    return reply.code(200).send(rows);
  });

  app.get('/presets/:id', async (req, reply) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return reply.code(400).send({ error: 'invalid id' });
    }
    const row = db
      .prepare('SELECT id, name, minutes, seconds, created_at FROM timer_presets WHERE id = ?')
      .get(id);
    if (!row) {
      return reply.code(404).send({ error: 'not found' });
    }
    return reply.code(200).send(row);
  });

  app.post('/presets', async (req, reply) => {
    const body = req.body || {};
    const name = typeof body.name === 'string' ? body.name.trim() : '';
    const minutes = Number(body.minutes);
    const seconds = Number(body.seconds);

    if (!name) {
      return reply.code(400).send({ error: 'name is required' });
    }
    if (!validate(minutes, seconds)) {
      return reply
        .code(400)
        .send({ error: 'minutes and seconds must be integers between 0 and 59' });
    }
    if (minutes === 0 && seconds === 0) {
      return reply.code(400).send({ error: 'duration must be greater than zero' });
    }

    const info = db
      .prepare('INSERT INTO timer_presets (name, minutes, seconds) VALUES (?, ?, ?)')
      .run(name, minutes, seconds);

    const row = db
      .prepare('SELECT id, name, minutes, seconds, created_at FROM timer_presets WHERE id = ?')
      .get(info.lastInsertRowid);

    return reply.code(201).send(row);
  });

  app.delete('/presets/:id', async (req, reply) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return reply.code(400).send({ error: 'invalid id' });
    }
    const info = db.prepare('DELETE FROM timer_presets WHERE id = ?').run(id);
    if (info.changes === 0) {
      return reply.code(404).send({ error: 'not found' });
    }
    return reply.code(200).send({ ok: true });
  });
}
