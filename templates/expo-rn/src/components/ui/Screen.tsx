import React from 'react';
import { SafeAreaView, ScrollView, StyleSheet, ViewProps } from 'react-native';

export interface ScreenProps extends ViewProps {
  children?: React.ReactNode;
}

/** The scrollable, safe-area screen container every feature mounts inside. */
export function Screen({ children, style, ...rest }: ScreenProps) {
  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={[styles.content, style]} {...rest}>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#f9fafb' },
  content: { padding: 16 },
});
