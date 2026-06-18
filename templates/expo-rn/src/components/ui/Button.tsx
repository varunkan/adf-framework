import React from 'react';
import { Pressable, Text, StyleSheet, PressableProps } from 'react-native';

export interface ButtonProps extends PressableProps {
  /** Visible label. */
  title: string;
  variant?: 'primary' | 'secondary' | 'danger';
}

/** A pressable button. `accessibilityRole="button"` makes it a real, detectable
 *  control on every platform (and react-native-web renders it as role="button"). */
export function Button({ title, variant = 'primary', style, ...rest }: ButtonProps) {
  return (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.base,
        styles[variant],
        pressed && styles.pressed,
        style as object,
      ]}
      {...rest}
    >
      <Text style={[styles.label, variant === 'secondary' && styles.labelDark]}>{title}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: { paddingVertical: 12, paddingHorizontal: 16, borderRadius: 8, alignItems: 'center' },
  primary: { backgroundColor: '#2563eb' },
  secondary: { backgroundColor: '#e5e7eb' },
  danger: { backgroundColor: '#dc2626' },
  pressed: { opacity: 0.8 },
  label: { color: '#ffffff', fontWeight: '600' },
  labelDark: { color: '#111827' },
});
