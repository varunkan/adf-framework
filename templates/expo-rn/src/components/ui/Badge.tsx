import React from 'react';
import { View } from 'react-native';
import { useTheme } from '../../theme';
import { Text } from './Text';

export interface BadgeProps {
  label: string | number;
  tone?: 'primary' | 'success' | 'danger' | 'warning';
}

/** A small themed status/count pill. */
export function Badge({ label, tone = 'primary' }: BadgeProps) {
  const t = useTheme();
  return (
    <View
      style={{
        backgroundColor: t.colors[tone],
        borderRadius: t.radius.full,
        paddingHorizontal: t.spacing.sm,
        paddingVertical: 2,
        minWidth: 20,
        alignItems: 'center',
      }}
    >
      <Text variant="caption" style={{ color: t.colors.onPrimary }}>
        {String(label)}
      </Text>
    </View>
  );
}
