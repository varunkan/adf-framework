import { useCallback, useEffect, useState } from 'react';
import {
  Habit,
  listHabits,
  createHabit,
  deleteHabit,
  getHabit,
  markHabitDone,
} from '../db';

export interface UseHabitsResult {
  items: Habit[];
  loading: boolean;
  error: string | null;
  create: (name: string) => Promise<void>;
  remove: (id: number) => Promise<void>;
  markDone: (id: number) => Promise<void>;
  reload: () => Promise<void>;
}

export function useHabits(): UseHabitsResult {
  const [items, setItems] = useState<Habit[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listHabits();
      setItems(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load habits');
    } finally {
      setLoading(false);
    }
  }, []);

  const create = useCallback(
    async (name: string) => {
      const trimmed = name.trim();
      if (!trimmed) {
        setError('Habit name is required');
        return;
      }
      try {
        await createHabit(trimmed);
        await reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to create habit');
      }
    },
    [reload]
  );

  const remove = useCallback(
    async (id: number) => {
      try {
        await deleteHabit(id);
        await reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to delete habit');
      }
    },
    [reload]
  );

  const markDone = useCallback(
    async (id: number) => {
      try {
        await markHabitDone(id);
        await reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to mark done');
      }
    },
    [reload]
  );

  useEffect(() => {
    reload();
  }, [reload]);

  return { items, loading, error, create, remove, markDone, reload };
}

export interface UseHabitResult {
  habit: Habit | null;
  loading: boolean;
  error: string | null;
  markDone: () => Promise<void>;
  reload: () => Promise<void>;
}

export function useHabit(id: number): UseHabitResult {
  const [habit, setHabit] = useState<Habit | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const row = await getHabit(id);
      setHabit(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load habit');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const markDone = useCallback(async () => {
    try {
      const updated = await markHabitDone(id);
      setHabit(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to mark done');
    }
  }, [id]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { habit, loading, error, markDone, reload };
}
