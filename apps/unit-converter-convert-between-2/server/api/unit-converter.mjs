import { db } from '../db.mjs';

const METERS_TO_FEET = 3.28084;

export function convert(direction, value) {
  if (direction === 'm-to-ft') {
    return value * METERS_TO_FEET;
  }
  if (direction === 'ft-to-m') {
    return value / METERS_TO_FEET;
  }
  return null;
}

export default async function unitConverter(app) {
  app.post('/convert', async (request, reply) => {
    const body = request.body || {};
    const { direction, value } = body;

    if (direction !== 'm-to-ft' && direction !== 'ft-to-m') {
      return reply.code(400).send({ error: 'direction must be "m-to-ft" or "ft-to-m"' });
    }

    const num = typeof value === 'number' ? value : Number(value);
    if (value === null || value === undefined || value === '' || Number.isNaN(num) || !Number.isFinite(num)) {
      return reply.code(400).send({ error: 'value must be a finite number' });
    }

    const result = convert(direction, num);
    if (result === null) {
      return reply.code(400).send({ error: 'invalid direction' });
    }

    const rounded = Math.round(result * 1e6) / 1e6;

    db.prepare(
      'INSERT INTO conversions (direction, input_value, output_value) VALUES (?, ?, ?)'
    ).run(direction, num, rounded);

    return reply.code(201).send({
      direction,
      input: num,
      output: rounded,
    });
  });

  app.get('/conversions', async (request, reply) => {
    const rows = db
      .prepare('SELECT id, direction, input_value, output_value, created_at FROM conversions ORDER BY id DESC LIMIT 50')
      .all();
    return reply.code(200).send(rows);
  });
}
