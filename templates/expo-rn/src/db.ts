// Local persistence via expo-sqlite (async API). The mobile app is self-contained
// — there is no server. The generated feature replaces this with its own schema +
// typed helpers. NEVER store a plaintext password column here (the policy gate
// fails the build) — hash it (see src/auth.ts when the feature needs auth).
import * as SQLite from 'expo-sqlite';

export interface Item {
  id: number;
  title: string;
}

let _db: SQLite.SQLiteDatabase | null = null;

export async function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!_db) {
    _db = await SQLite.openDatabaseAsync('app.db');
    await _db.execAsync(
      "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, " +
        "title TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));"
    );
  }
  return _db;
}

export async function listItems(): Promise<Item[]> {
  const db = await getDb();
  return db.getAllAsync<Item>('SELECT id, title FROM items ORDER BY id DESC');
}

export async function addItem(title: string): Promise<void> {
  const db = await getDb();
  await db.runAsync('INSERT INTO items (title) VALUES (?)', title);
}

export async function removeItem(id: number): Promise<void> {
  const db = await getDb();
  await db.runAsync('DELETE FROM items WHERE id = ?', id);
}
