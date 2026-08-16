import React from 'react';
import { View, Text, ViewProps } from 'react-native';
import { useTheme } from '../../theme';

export interface CardProps extends ViewProps {
  title?: string;
  children?: React.ReactNode;
}

/** A themed, bordered surface that groups related content. */
export function Card({ title, children, style, ...rest }: CardProps) {
  const t = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: t.colors.surface,
          borderRadius: t.radius.lg,
          padding: t.spacing.lg,
          marginBottom: t.spacing.md,
          borderWidth: 1,
          borderColor: t.colors.border,
        },
        style,
      ]}
      {...rest}
    >
      {title ? (
        <Text style={{ fontSize: t.type.h2.fontSize, fontWeight: t.type.h2.fontWeight, color: t.colors.text, marginBottom: t.spacing.sm }}>
          {title}
        </Text>
      ) : null}
      {children}
    </View>
  );
}
