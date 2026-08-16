// Root navigation layout (Expo Router, file-based routing). Every file under
// `app/` is a screen; this Stack themes the navigation chrome. The generated
// feature adds/replaces screens here (e.g. app/(tabs)/_layout.tsx for tabs).
import React from 'react';
import { Stack } from 'expo-router';
import { useTheme } from '../src/theme';

export default function RootLayout() {
  const t = useTheme();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: t.colors.surface },
        headerTintColor: t.colors.text,
        headerTitleStyle: { fontWeight: '700' },
        contentStyle: { backgroundColor: t.colors.bg },
      }}
    >
      <Stack.Screen name="index" options={{ title: 'Items' }} />
      <Stack.Screen name="[id]" options={{ title: 'Detail' }} />
    </Stack>
  );
}
