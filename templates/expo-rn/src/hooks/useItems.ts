// Sample data hook — components call this, never the db directly. Errors are
// caught (so the UI still renders even where SQLite isn't available, e.g. a web
// render check). The generated feature replaces this with use<Feature>.
import { useCallback, useEffect, useState } from 'react';
import { Item, addItem, listItems, removeItem } from '../db';

export function useItems() {
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setItems(await listItems());
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const create = useCallback(
    async (title: string) => {
      try {
        await addItem(title);
        await reload();
      } catch (e) {
        setError(String(e));
      }
    },
    [reload]
  );

  const remove = useCallback(
    async (id: number) => {
      try {
        await removeItem(id);
        await reload();
      } catch (e) {
        setError(String(e));
      }
    },
    [reload]
  );

  return { items, error, create, remove, reload };
}
