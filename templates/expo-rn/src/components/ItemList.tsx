// SAMPLE feature component — stripped on scaffold; the generated feature replaces
// it. Demonstrates the discipline: props-driven, composes the shipped ui/ primitives,
// gets data from a hook (never touches the db directly).
import React, { useState } from 'react';
import { View, Text, FlatList, StyleSheet } from 'react-native';
import { Button, Card, Input } from './ui';
import { useItems } from '../hooks/useItems';

export interface ItemListProps {}

export function ItemList(_props: ItemListProps) {
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
      <Text style={styles.heading}>Items</Text>
      <FlatList
        data={items}
        keyExtractor={(it) => String(it.id)}
        renderItem={({ item }) => (
          <Card>
            <View style={styles.row}>
              <Text style={styles.itemTitle}>{item.title}</Text>
              <Button title="Delete" variant="danger" onPress={() => remove(item.id)} />
            </View>
          </Card>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  heading: { fontSize: 18, fontWeight: '700', marginVertical: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  itemTitle: { fontSize: 15 },
});
