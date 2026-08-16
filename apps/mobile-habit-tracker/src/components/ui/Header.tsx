import React from 'react';
import { View, Pressable } from 'react-native';
import { useTheme } from '../../theme';
import { Text } from './Text';
import { Icon, IconName } from './Icon';

export interface HeaderProps {
  title: string;
  onBack?: () => void;
  action?: { icon: IconName; onPress: () => void; label?: string };
}

/** A screen header: an optional back affordance, the title (renders as a real
 *  heading), and an optional trailing action. */
export function Header({ title, onBack, action }: HeaderProps) {
  const t = useTheme();
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: t.spacing.sm,
        marginBottom: t.spacing.md,
        gap: t.spacing.sm,
      }}
    >
      {onBack ? (
        <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={onBack}>
          <Icon name="chevron-back" />
        </Pressable>
      ) : null}
      <Text variant="h1" style={{ flex: 1 }}>
        {title}
      </Text>
      {action ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={action.label ?? 'Action'}
          onPress={action.onPress}
        >
          <Icon name={action.icon} color={t.colors.primary} />
        </Pressable>
      ) : null}
    </View>
  );
}
