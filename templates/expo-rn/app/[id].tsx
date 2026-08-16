// SAMPLE detail screen (dynamic route "/[id]") — stripped on scaffold. Reads the
// route param, shows the record, and acts on it (delete → back). The generated
// feature replaces it with its own detail route.
import React from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Screen, Card, Button, Text } from '../src/components/ui';
import { useItems } from '../src/hooks/useItems';

export default function ItemDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { items, remove } = useItems();
  const item = items.find((x) => String(x.id) === String(id));

  if (!item) {
    return (
      <Screen>
        <Text variant="h1">Not found</Text>
        <Text variant="caption">No item with id {String(id)}.</Text>
      </Screen>
    );
  }

  return (
    <Screen>
      <Text variant="h1">{item.title}</Text>
      <Card title="Details">
        <Text variant="body">ID: {item.id}</Text>
      </Card>
      <Button
        title="Delete"
        variant="danger"
        onPress={() => {
          remove(item.id);
          router.back();
        }}
      />
    </Screen>
  );
}
