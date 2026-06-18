import React from 'react';
import { SafeAreaView, ScrollView, ViewProps } from 'react-native';
import { useTheme } from '../../theme';

export interface ScreenProps extends ViewProps {
  children?: React.ReactNode;
}

/** The themed, scrollable, safe-area screen container every feature mounts inside. */
export function Screen({ children, style, ...rest }: ScreenProps) {
  const t = useTheme();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.colors.bg }}>
      <ScrollView contentContainerStyle={[{ padding: t.spacing.lg }, style]} {...rest}>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}
