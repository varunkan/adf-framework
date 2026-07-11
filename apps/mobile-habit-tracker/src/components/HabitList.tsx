import React from 'react';
import { View } from 'react-native';
import { Habit } from '../db';
import { ListItem, Badge, EmptyState, Button } from './ui';
import { useTheme } from '../theme';

export interface HabitListProps {
  habits: Habit[];
  onOpen: (habit: Habit) => void;
  onDelete: (id: number) => void;
}

export function HabitList({ habits, onOpen, onDelete }: HabitListProps) {
  const t = useTheme();

  if (habits.length === 0) {
    return (
      <EmptyState
        icon="checkmark-done-outline"
        title="No habits yet"
        message="Add a habit above to start tracking your streaks."
      />
    );
  }

  return (
    <View style={{ gap: t.spacing.sm }}>
      {habits.map((habit) => (
        <View
          key={habit.id}
          style={{ flexDirection: 'row', alignItems: 'center', gap: t.spacing.sm }}
        >
          <View style={{ flex: 1 }}>
            <ListItem
              title={habit.name}
              subtitle={`Streak: ${habit.streak} day${habit.streak === 1 ? '' : 's'}`}
              showChevron
              onPress={() => onOpen(habit)}
            />
          </View>
          <Badge label={String(habit.streak)} />
          <Button
            title="Delete"
            variant="danger"
            onPress={() => onDelete(habit.id)}
            accessibilityLabel={`Delete ${habit.name}`}
          />
        </View>
      ))}
    </View>
  );
}
