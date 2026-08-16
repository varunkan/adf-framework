import React from 'react';
import { View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Screen, Header, Text, Card, Button, Badge } from '../src/components/ui';
import { useHabit } from '../src/hooks/useHabits';
import { useTheme } from '../src/theme';

export default function HabitDetailScreen() {
  const t = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ id: string }>();
  const id = Number(params.id);
  const { habit, loading, error, markDone } = useHabit(id);

  return (
    <Screen>
      <Header title="Habit Detail" onBack={() => router.back()} />
      <View style={{ gap: t.spacing.md }}>
        {loading ? (
          <Text variant="body">Loading…</Text>
        ) : !habit ? (
          <Text variant="body">Habit not found.</Text>
        ) : (
          <>
            <Card>
              <View style={{ gap: t.spacing.sm }}>
                <Text variant="h1">{habit.name}</Text>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: t.spacing.sm }}>
                  <Text variant="label">Current streak</Text>
                  <Badge label={`${habit.streak}`} />
                </View>
                <Text variant="caption">
                  {habit.last_done
                    ? `Last done: ${habit.last_done}`
                    : 'Not done yet'}
                </Text>
              </View>
            </Card>

            <Button
              title="Mark done for today"
              variant="primary"
              onPress={markDone}
              accessibilityLabel="Mark habit done for today"
            />

            {error ? (
              <Text variant="caption" style={{ color: t.colors.danger }}>
                {error}
              </Text>
            ) : null}
          </>
        )}
      </View>
    </Screen>
  );
}
