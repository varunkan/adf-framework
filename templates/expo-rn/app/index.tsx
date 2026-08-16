// SAMPLE list screen (route "/") — stripped on scaffold; the generated feature
// replaces it. Demonstrates the list→detail pattern: composes the themed kit,
// reads data from a hook (never the db directly), and navigates with the router.
import React, { useState } from 'react';
import { useRouter } from 'expo-router';
import { Screen, Card, Input, Button, ListItem, EmptyState } from '../src/components/ui';
import { useItems } from '../src/hooks/useItems';

export default function ItemsScreen() {
  const router = useRouter();
  const { items, create } = useItems();
  const [title, setTitle] = useState('');

  const add = () => {
    if (title.trim()) {
      create(title.trim());
      setTitle('');
    }
  };

  return (
    <Screen>
      <Card title="Add item">
        <Input label="Title" placeholder="Enter a title" value={title} onChangeText={setTitle} />
        <Button title="Add" onPress={add} />
      </Card>
      {items.length === 0 ? (
        <EmptyState title="No items yet" message="Add your first item above" />
      ) : (
        items.map((item) => (
          <ListItem
            key={item.id}
            title={item.title}
            showChevron
            onPress={() => router.push(`/${item.id}`)}
          />
        ))
      )}
    </Screen>
  );
}
