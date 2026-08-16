import { db } from '../db.mjs';

function calculate(billAmount, tipPercent, people) {
  const tipAmount = billAmount * (tipPercent / 100);
  const totalAmount = billAmount + tipAmount;
  const perPerson = totalAmount / people;
  return {
    tip_amount: round2(tipAmount),
    total_amount: round2(totalAmount),
    per_person: round2(perPerson),
  };
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function validate(body) {
  const billAmount = Number(body?.bill_amount);
  const tipPercent = Number(body?.tip_percent);
  const people = Number(body?.people);

  if (!Number.isFinite(billAmount) || billAmount < 0) {
    return { error: 'bill_amount must be a non-negative number' };
  }
  if (!Number.isFinite(tipPercent) || tipPercent < 0) {
    return { error: 'tip_percent must be a non-negative number' };
  }
  if (!Number.isInteger(people) || people < 1) {
    return { error: 'people must be a positive integer' };
  }
  return { billAmount, tipPercent, people };
}

export default async function tipCalculatorBillAmount(app) {
  app.post('/tip/calculate', async (request, reply) => {
    const v = validate(request.body);
    if (v.error) return reply.code(400).send({ error: v.error });

    const result = calculate(v.billAmount, v.tipPercent, v.people);
    return reply.code(200).send({
      bill_amount: round2(v.billAmount),
      tip_percent: v.tipPercent,
      people: v.people,
      ...result,
    });
  });

  app.post('/tip/calculations', async (request, reply) => {
    const v = validate(request.body);
    if (v.error) return reply.code(400).send({ error: v.error });

    const result = calculate(v.billAmount, v.tipPercent, v.people);
    const info = db
      .prepare(
        `INSERT INTO tip_calculations
          (bill_amount, tip_percent, people, tip_amount, total_amount, per_person)
         VALUES (?, ?, ?, ?, ?, ?)`
      )
      .run(
        round2(v.billAmount),
        v.tipPercent,
        v.people,
        result.tip_amount,
        result.total_amount,
        result.per_person
      );

    const row = db
      .prepare('SELECT * FROM tip_calculations WHERE id = ?')
      .get(info.lastInsertRowid);
    return reply.code(201).send(row);
  });

  app.get('/tip/calculations', async (_request, reply) => {
    const rows = db
      .prepare('SELECT * FROM tip_calculations ORDER BY id DESC')
      .all();
    return reply.code(200).send(rows);
  });

  app.get('/tip/calculations/:id', async (request, reply) => {
    const id = Number(request.params.id);
    if (!Number.isInteger(id)) {
      return reply.code(400).send({ error: 'invalid id' });
    }
    const row = db
      .prepare('SELECT * FROM tip_calculations WHERE id = ?')
      .get(id);
    if (!row) return reply.code(404).send({ error: 'not found' });
    return reply.code(200).send(row);
  });
}
