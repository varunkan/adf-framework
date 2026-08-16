import React from 'react';
import { render, fireEvent, waitFor, act } from '@testing-library/react-native';
import { renderHook } from '@testing-library/react-native';

jest.mock('expo-router', () => {
  const mockPush = jest.fn();
  const mockBack = jest.fn();
  return {
    useRouter: () => ({ push: mockPush, back: mockBack }),
    useLocalSearchParams: () => ({ id: '1' }),
    __mockPush: mockPush,
    Stack: ({ children }: { children?: React.ReactNode }) => children ?? null,
  };
});

jest.mock('../src/db', () => {
  let mockStore: any[] = [];
  let mockNextId = 1;
  const todayStr = () => new Date().toISOString().slice(0, 10);

  return {
    listHabits: async () => [...mockStore].sort((a, b) => b.id - a.id),
    getHabit: async (id: number) => mockStore.find((h) => h.id === id) ?? null,
    createHabit: async (name: string) => {
      const row = {
        id: mockNextId++,
        name,
        streak: 0,
        last_done: null,
        created_at: new Date().toISOString(),
      };
      mockStore.push(row);
      return row;
    },
    deleteHabit: async (id: number) => {
      mockStore = mockStore.filter((h) => h.id !== id);
    },
    markHabitDone: async (id: number) => {
      const habit = mockStore.find((h) => h.id === id);
      if (!habit) return null;
      const today = todayStr();
      if (habit.last_done === today) return habit;
      habit.streak += 1;
      habit.last_done = today;
      return habit;
    },
    __reset: () => {
      mockStore = [];
      mockNextId = 1;
    },
    __getStore: () => mockStore,
    __seed: (rows: any[]) => {
      mockStore = rows;
      mockNextId = rows.reduce((m, r) => Math.max(m, r.id), 0) + 1;
    },
  };
});

import HomeScreen from '../app/index';
import HabitDetailScreen from '../app/[id]';
import { useHabits } from '../src/hooks/useHabits';

const db = require('../src/db');

beforeEach(() => {
  db.__reset();
});

describe('HomeScreen', () => {
  it('shows empty state when no habits', async () => {
    const { findByText } = render(<HomeScreen />);
    expect(await findByText('No habits yet')).toBeTruthy();
  });

  it('adds a new habit via the form', async () => {
    const { getByPlaceholderText, getByLabelText, findByText } = render(<HomeScreen />);
    const input = getByPlaceholderText('New habit name');
    fireEvent.changeText(input, 'Drink Water');
    fireEvent.press(getByLabelText('Add habit'));
    expect(await findByText('Drink Water')).toBeTruthy();
  });

  it('does not add an empty habit', async () => {
    const { getByLabelText, findByText } = render(<HomeScreen />);
    fireEvent.press(getByLabelText('Add habit'));
    expect(await findByText('No habits yet')).toBeTruthy();
  });
});

describe('HabitDetailScreen', () => {
  it('shows habit not found when absent', async () => {
    const { findByText } = render(<HabitDetailScreen />);
    expect(await findByText('Habit not found.')).toBeTruthy();
  });

  it('marks a habit done and increments streak', async () => {
    db.__seed([
      { id: 1, name: 'Exercise', streak: 0, last_done: null, created_at: '2024-01-01' },
    ]);
    const { findByText, getByLabelText } = render(<HabitDetailScreen />);
    expect(await findByText('Exercise')).toBeTruthy();
    fireEvent.press(getByLabelText('Mark habit done for today'));
    await waitFor(() => {
      expect(db.__getStore()[0].streak).toBe(1);
    });
  });
});

describe('useHabits hook', () => {
  it('creates and lists habits', async () => {
    const { result } = renderHook(() => useHabits());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.create('Read');
    });

    await waitFor(() => {
      expect(result.current.items.map((i) => i.name)).toContain('Read');
    });
  });

  it('sets error when creating empty habit', async () => {
    const { result } = renderHook(() => useHabits());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.create('   ');
    });

    await waitFor(() => {
      expect(result.current.error).toBe('Habit name is required');
    });
    expect(result.current.items).toHaveLength(0);
  });

  it('removes a habit', async () => {
    db.__seed([
      { id: 5, name: 'Meditate', streak: 2, last_done: null, created_at: '2024-01-01' },
    ]);
    const { result } = renderHook(() => useHabits());
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    await act(async () => {
      await result.current.remove(5);
    });

    await waitFor(() => expect(result.current.items).toHaveLength(0));
  });
});
