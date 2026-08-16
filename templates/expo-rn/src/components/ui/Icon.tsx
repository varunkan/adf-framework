import React from 'react';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';

export type IconName = React.ComponentProps<typeof Ionicons>['name'];

export interface IconProps {
  name: IconName;
  /** A token size (sm/md/lg) or an explicit pixel size. */
  size?: 'sm' | 'md' | 'lg' | number;
  color?: string;
  accessibilityLabel?: string;
}

/** A themed icon (Ionicons, ships with Expo — no extra dependency). */
export function Icon({ name, size = 'md', color, accessibilityLabel }: IconProps) {
  const t = useTheme();
  const px = typeof size === 'number' ? size : t.icon[size];
  return (
    <Ionicons
      name={name}
      size={px}
      color={color ?? t.colors.text}
      accessibilityLabel={accessibilityLabel}
    />
  );
}
