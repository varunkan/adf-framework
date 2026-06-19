import React from 'react';
import { Pressable, View } from 'react-native';
import { useTheme } from '../../theme';
import { Text } from './Text';
import { Icon } from './Icon';

export interface ListItemProps {
  title: string;
  subtitle?: string;
  onPress?: () => void;
  trailing?: React.ReactNode;
  /** Show a chevron to signal it navigates (list → detail). */
  showChevron?: boolean;
}

/** A themed row for lists. Pressable (a real button) when `onPress` is given. */
export function ListItem({ title, subtitle, onPress, trailing, showChevron }: ListItemProps) {
  const t = useTheme();
  const inner = (
    <>
      <View style={{ flex: 1 }}>
        <Text variant="body">{title}</Text>
        {subtitle ? <Text variant="caption">{subtitle}</Text> : null}
      </View>
      {trailing}
      {showChevron ? <Icon name="chevron-forward" size="sm" color={t.colors.textMuted} /> : null}
    </>
  );
  const style = {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    paddingVertical: t.spacing.md,
    paddingHorizontal: t.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.border,
    gap: t.spacing.sm,
  };
  return onPress ? (
    <Pressable accessibilityRole="button" onPress={onPress} style={style}>
      {inner}
    </Pressable>
  ) : (
    <View style={style}>{inner}</View>
  );
}
