// Composition ROOT (default export, registered by Expo's AppEntry). The generated
// feature overwrites this to arrange its own components inside a Screen.
import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { Text, StyleSheet } from 'react-native';
import { Screen } from './src/components/ui';
import { ItemList } from './src/components/ItemList';

export default function App() {
  return (
    <Screen>
      <StatusBar style="auto" />
      <Text style={styles.h1}>Items</Text>
      <ItemList />
    </Screen>
  );
}

const styles = StyleSheet.create({
  h1: { fontSize: 24, fontWeight: '800', marginBottom: 12 },
});
