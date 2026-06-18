// Composition ROOT (default export, registered by Expo's AppEntry). The generated
// feature overwrites this to arrange its own components inside a Screen.
import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { Screen, Text } from './src/components/ui';
import { ItemList } from './src/components/ItemList';

export default function App() {
  return (
    <Screen>
      <StatusBar style="auto" />
      <Text variant="h1">Items</Text>
      <ItemList />
    </Screen>
  );
}
