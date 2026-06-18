// SAMPLE feature component — stripped on scaffold; the generated feature replaces
// it. Demonstrates the discipline: props-driven, composes the shipped THEMED ui/
// primitives (Card/Input/Button/Text), gets data from a hook (never touches the db
// directly), uses NO raw hex (the policy gate enforces it — colors come from theme).
import React, { useState } from 'react';
import { View } from 'react-native';
import { Button, Card, Input, Text } from './ui';
import { useTheme } from '../theme';
import { useItems } from '../hooks/useItems';

export interface ItemListProps {}

export function ItemList(_props: ItemListProps) {
  const t = useTheme();
  const { items, create, remove } = useItems();
  const [title, setTitle] = useState('');

  const submit = () => {
    if (title.trim()) {
      create(title.trim());
      setTitle('');
    }
  };

  return (
    <View>
      <Card title="Add item">
        <Input
          label="Title"
          placeholder="Enter a title"
          value={title}
          onChangeText={setTitle}
        />
        <Button title="Add" onPress={submit} />
      </Card>
      <Text variant="h2" style={{ marginVertical: t.spacing.sm }}>
        Items
      </Text>
      {items.map((item) => (
        <Card key={item.id}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text variant="body">{item.title}</Text>
            <Button title="Delete" variant="danger" onPress={() => remove(item.id)} />
          </View>
        </Card>
      ))}
    </View>
  );
}
