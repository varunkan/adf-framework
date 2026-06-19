// SAMPLE test — stripped on scaffold. The CANONICAL pattern for testing a CRUD
// feature: a STATEFUL mock of the data layer (`src/db`) plus tests that drive the
// screen AND the hook that read from it. Copy this shape for your feature's db.
//
// THE ONE RULE that trips everybody up — jest hoists `jest.mock(...)` ABOVE every
// import and `let`/`const` in this file, so its factory runs FIRST, before any
// module-scope variable exists. Referencing an out-of-scope variable from inside
// the factory throws:
//   "The module factory of jest.mock() is not allowed to reference any
//    out-of-scope variables. Invalid variable access: store"
// jest's babel hoist allows ONE escape hatch: variables whose names are prefixed
// with `mock` (case-insensitive) may be referenced. So the stateful store lives
// in a `mock`-prefixed binding, declared INSIDE the factory and exposed to the
// test via a `mock`-prefixed accessor — never a bare `let store = []` referenced
// inside the factory.
import React from 'react';
import { render, fireEvent, waitFor, act } from '@testing-library/react-native';

// Stateful mock of the async data layer (src/db). Everything the factory touches
// is either declared inside the factory or named `mock*` so jest's hoist allows
// it. `__getStore` / `__reset` are `mock`-prefixed test handles (allowed) used to
// seed + clear state between tests.
jest.mock('../src/db', () => {
  let mockStore: { id: number; title: string }[] = [];
  let mockNextId = 1;
  return {
    __esModule: true,
    listItems: async () => [...mockStore].sort((a, b) => b.id - a.id),
    addItem: async (title: string) => {
      mockStore.push({ id: mockNextId++, title });
    },
    removeItem: async (id: number) => {
      mockStore = mockStore.filter((it) => it.id !== id);
    },
    // mock-prefixed handles the test uses to seed / inspect / reset the store.
    __getStore: () => mockStore,
    __reset: () => {
      mockStore = [];
      mockNextId = 1;
    },
  };
});

// Same inline pattern for expo-router (navigation hooks). The spies are mock-prefixed
// so the factory may close over them and the test can assert on them.
const mockPush = jest.fn();
const mockBack = jest.fn();
let mockParams: { id: string } = { id: '1' };
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, back: mockBack }),
  useLocalSearchParams: () => mockParams,
}));

// Import the units under test AFTER the mocks (jest still hoists the mocks above
// these). Import the mocked db too, to drive its `mock`-prefixed test handles.
import ItemsScreen from '../app/index';
import { useItems } from '../src/hooks/useItems';
import { renderHook } from '@testing-library/react-native';
import * as db from '../src/db';

const dbMock = db as unknown as {
  __getStore: () => { id: number; title: string }[];
  __reset: () => void;
};

beforeEach(() => {
  dbMock.__reset();
  mockPush.mockClear();
  mockBack.mockClear();
  mockParams = { id: '1' };
});

describe('items screen (reads the stateful db mock)', () => {
  it('shows the empty state, then the item it just added', async () => {
    const { getByText, getByPlaceholderText, findByText } = render(<ItemsScreen />);
    // Empty state first (the hook loaded an empty store).
    expect(await findByText('No items yet')).toBeTruthy();

    fireEvent.changeText(getByPlaceholderText('Enter a title'), 'Buy milk');
    fireEvent.press(getByText('Add'));

    // The screen re-reads the mock and renders the new row.
    expect(await findByText('Buy milk')).toBeTruthy();
    // The mutation actually hit the stateful store.
    expect(dbMock.__getStore().map((it) => it.title)).toContain('Buy milk');
  });
});

describe('useItems hook (reads + mutates the stateful db mock)', () => {
  it('loads items and creates one', async () => {
    const { result } = renderHook(() => useItems());

    // Initial async load resolves to the (empty) store.
    await waitFor(() => expect(result.current.items).toEqual([]));

    await act(async () => {
      await result.current.create('Walk the dog');
    });

    await waitFor(() =>
      expect(result.current.items.map((it) => it.title)).toContain('Walk the dog')
    );
  });
});
