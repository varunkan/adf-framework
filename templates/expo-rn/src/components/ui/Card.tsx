import React from 'react';
import { View, Text, StyleSheet, ViewProps } from 'react-native';

export interface CardProps extends ViewProps {
  title?: string;
  children?: React.ReactNode;
}

/** A bordered surface that groups related content. */
export function Card({ title, children, style, ...rest }: CardProps) {
  return (
    <View style={[styles.card, style]} {...rest}>
      {title ? <Text style={styles.title}>{title}</Text> : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  title: { fontSize: 16, fontWeight: '700', marginBottom: 8 },
});
