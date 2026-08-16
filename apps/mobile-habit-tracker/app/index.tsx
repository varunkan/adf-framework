import React from 'react';
import { View } from 'react-native';
import { useRouter } from 'expo-router';
import { Screen, Header, Text, Card } from '../src/components/ui';
import { HabitForm } from '../src/components/HabitForm';
import { HabitList } from '../src/components/HabitList';
import { useHabits } from '../src/hooks/useHabits';
import { useTheme } from '../src/theme';

export default function HomeScreen() {
  const t = useTheme();
  const router = useRouter();
  const { items, loading, error, create, remove } = useHabits();

  return (
    <Screen>
      <Header title="Habit Tracker" />
      <View style={{ gap: t.spacing.md }}>
        <Card>
          <HabitForm onSubmit={create} />
        </Card>

        {error ? (
          <Text variant="caption" style={{ color: t.colors.danger }}>
            {error}
          </Text>
        ) : null}

        {loading ? (
          <Text variant="body">Loading…</Text>
        ) : (
          <HabitList
            habits={items}
            onOpen={(habit) => router.push(`/${habit.id}`)}
            onDelete={remove}
          />
        )}
      </View>
    </Screen>
  );
}
