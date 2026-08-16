import React from 'react';
import { Text as RNText, TextProps } from 'react-native';
import { useTheme } from '../../theme';

export type TextVariant = 'h1' | 'h2' | 'body' | 'caption' | 'label';

export interface AppTextProps extends TextProps {
  variant?: TextVariant;
}

/** Themed, semantic typography. `h1`/`h2` set `accessibilityRole="header"` so they
 *  render as a real heading (role="heading" on web) — detectable by the render gate
 *  and correct for screen readers. */
export function Text({ variant = 'body', style, ...rest }: AppTextProps) {
  const t = useTheme();
  const token = t.type[variant];
  const isHeading = variant === 'h1' || variant === 'h2';
  const color =
    variant === 'caption' || variant === 'label' ? t.colors.textMuted : t.colors.text;
  return (
    <RNText
      accessibilityRole={isHeading ? 'header' : undefined}
      style={[{ color, fontSize: token.fontSize, fontWeight: token.fontWeight }, style]}
      {...rest}
    />
  );
}
