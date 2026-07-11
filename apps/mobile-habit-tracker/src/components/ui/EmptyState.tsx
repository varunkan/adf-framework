import React from 'react';
import { View } from 'react-native';
import { useTheme } from '../../theme';
import { Text } from './Text';
import { Icon, IconName } from './Icon';

export interface EmptyStateProps {
  icon?: IconName;
  title: string;
  message?: string;
}

/** A themed empty/zero-data placeholder — the polished default when a list is empty. */
export function EmptyState({ icon = 'file-tray-outline', title, message }: EmptyStateProps) {
  const t = useTheme();
  return (
    <View style={{ alignItems: 'center', padding: t.spacing.xl, gap: t.spacing.sm }}>
      <Icon name={icon} size="lg" color={t.colors.textMuted} />
      <Text variant="h2">{title}</Text>
      {message ? (
        <Text variant="caption" style={{ textAlign: 'center' }}>
          {message}
        </Text>
      ) : null}
    </View>
  );
}
