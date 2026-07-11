import React, { useState } from 'react';
import { View } from 'react-native';
import { Input, Button } from './ui';
import { useTheme } from '../theme';

export interface HabitFormProps {
  onSubmit: (name: string) => void | Promise<void>;
}

export function HabitForm({ onSubmit }: HabitFormProps) {
  const t = useTheme();
  const [name, setName] = useState('');

  const handleSubmit = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    await onSubmit(trimmed);
    setName('');
  };

  return (
    <View style={{ flexDirection: 'row', gap: t.spacing.sm, alignItems: 'center' }}>
      <View style={{ flex: 1 }}>
        <Input
          placeholder="New habit name"
          value={name}
          onChangeText={setName}
          accessibilityLabel="Habit name input"
          onSubmitEditing={handleSubmit}
          returnKeyType="done"
        />
      </View>
      <Button
        title="Add"
        variant="primary"
        onPress={handleSubmit}
        accessibilityLabel="Add habit"
      />
    </View>
  );
}
