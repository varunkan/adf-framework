import { db } from '../db.mjs';

function round2(n) {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

export function compute(bill, tipPercent, people) {
  const tipAmount = round2((bill * tipPercent) / 100);
  const total = round2(bill + tipAmount);
  const perPerson = round2(total / people);
  return { tipAmount, total, perPerson };
}

export default async function tipCalculator(app) {
  app.post('/tip', async (request, reply) => {
    const body = request.body || {};
    const bill = Number(body.bill);
    const tipPercent = Number(body.tipPercent);
    const people = Number(body.people);

    if (!Number.isFinite(bill) || bill <= 0) {
      return reply.code(400).send({ error: 'bill must be a positive number' });
    }
    if (!Number.isFinite(tipPercent) || tipPercent < 0) {
      return reply.code(400).send({ error: 'tipPercent must be a non-negative number' });
    }
    if (!Number.isInteger(people) || people < 1) {
      return reply.code(400).send({ error: 'people must be a positive integer' });
    }

    const { tipAmount, total, perPerson } = compute(bill, tipPercent, people);

    const info = db
      .prepare(
        `INSERT INTO calculations (bill, tip_percent, people, tip_amount, total, per_person)
         VALUES (?, ?, ?, ?, ?, ?)`
      )
      .run(bill, tipPercent, people, tipAmount, total, perPerson);

    return reply.code(201).send({
      id: info.lastInsertRowid,
      bill,
      tipPercent,
      people,
      tipAmount,
      total,
      perPerson,
    });
  });

  app.get('/tip', async (_request, reply) => {
    const rows = db
      .prepare(
        `SELECT id, bill, tip_percent AS tipPercent, people,
                tip_amount AS tipAmount, total, per_person AS perPerson, created_at AS createdAt
         FROM calculations ORDER BY id DESC LIMIT 50`
      )
      .all();
    return reply.code(200).send(rows);
  });

  app.get('/tip/:id', async (request, reply) => {
    const id = Number(request.params.id);
    if (!Number.isInteger(id)) {
      return reply.code(400).send({ error: 'invalid id' });
    }
    const row = db
      .prepare(
        `SELECT id, bill, tip_percent AS tipPercent, people,
                tip_amount AS tipAmount, total, per_person AS perPerson, created_at AS createdAt
         FROM calculations WHERE id = ?`
      )
      .get(id);
    if (!row) {
      return reply.code(404).send({ error: 'not found' });
    }
    return reply.code(200).send(row);
  });
}
