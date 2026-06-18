import React from 'react';
import { Pressable, Text, PressableProps } from 'react-native';
import { useTheme } from '../../theme';

export interface ButtonProps extends PressableProps {
  /** Visible label. */
  title: string;
  variant?: 'primary' | 'secondary' | 'danger';
}

/** A themed pressable button. `accessibilityRole="button"` makes it a real,
 *  detectable control on every platform (react-native-web renders role="button"). */
export function Button({ title, variant = 'primary', style, ...rest }: ButtonProps) {
  const t = useTheme();
  const bg =
    variant === 'danger' ? t.colors.danger
      : variant === 'secondary' ? t.colors.surfaceAlt
        : t.colors.primary;
  const fg =
    variant === 'danger' ? t.colors.onDanger
      : variant === 'secondary' ? t.colors.text
        : t.colors.onPrimary;
  return (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [
        {
          backgroundColor: bg,
          paddingVertical: t.spacing.md,
          paddingHorizontal: t.spacing.lg,
          borderRadius: t.radius.md,
          alignItems: 'center',
        },
        pressed && { opacity: 0.85 },
        style as object,
      ]}
      {...rest}
    >
      <Text style={{ color: fg, fontWeight: '600' }}>{title}</Text>
    </Pressable>
  );
}
