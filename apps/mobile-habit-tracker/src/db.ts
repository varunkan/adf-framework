import * as SQLite from 'expo-sqlite';

export interface Habit {
  id: number;
  name: string;
  streak: number;
  last_done: string | null;
  created_at: string;
}

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = SQLite.openDatabaseAsync('habits.db').then(async (db) => {
      await db.execAsync(
        `CREATE TABLE IF NOT EXISTS habits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          streak INTEGER NOT NULL DEFAULT 0,
          last_done TEXT,
          created_at TEXT
        );`
      );
      return db;
    });
  }
  return dbPromise;
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export async function listHabits(): Promise<Habit[]> {
  const db = await getDb();
  return db.getAllAsync<Habit>('SELECT * FROM habits ORDER BY id DESC;');
}

export async function getHabit(id: number): Promise<Habit | null> {
  const db = await getDb();
  const row = await db.getFirstAsync<Habit>('SELECT * FROM habits WHERE id = ?;', [id]);
  return row ?? null;
}

export async function createHabit(name: string): Promise<Habit> {
  const db = await getDb();
  const created_at = new Date().toISOString();
  const result = await db.runAsync(
    'INSERT INTO habits (name, streak, last_done, created_at) VALUES (?, 0, NULL, ?);',
    [name, created_at]
  );
  const row = await db.getFirstAsync<Habit>('SELECT * FROM habits WHERE id = ?;', [
    result.lastInsertRowId,
  ]);
  return row as Habit;
}

export async function deleteHabit(id: number): Promise<void> {
  const db = await getDb();
  await db.runAsync('DELETE FROM habits WHERE id = ?;', [id]);
}

export async function markHabitDone(id: number): Promise<Habit | null> {
  const db = await getDb();
  const habit = await getHabit(id);
  if (!habit) return null;
  const today = todayStr();
  if (habit.last_done === today) {
    return habit;
  }
  const newStreak = habit.streak + 1;
  await db.runAsync('UPDATE habits SET streak = ?, last_done = ? WHERE id = ?;', [
    newStreak,
    today,
    id,
  ]);
  return getHabit(id);
}
