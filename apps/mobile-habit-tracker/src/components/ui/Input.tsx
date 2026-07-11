import React from 'react';
import { View, Text, TextInput, TextInputProps } from 'react-native';
import { useTheme } from '../../theme';

export interface InputProps extends TextInputProps {
  /** Optional field label rendered above the input. */
  label?: string;
}

/** A themed, labelled text field. react-native-web renders `<TextInput>` as a real
 *  `<input>`, so it is detectable by the render gate. */
export function Input({ label, style, accessibilityLabel, ...rest }: InputProps) {
  const t = useTheme();
  return (
    <View style={{ marginBottom: t.spacing.md }}>
      {label ? (
        <Text style={{ marginBottom: t.spacing.xs, color: t.colors.text, fontWeight: '500' }}>
          {label}
        </Text>
      ) : null}
      <TextInput
        accessibilityLabel={accessibilityLabel ?? label}
        placeholderTextColor={t.colors.textMuted}
        style={[
          {
            borderWidth: 1,
            borderColor: t.colors.border,
            borderRadius: t.radius.md,
            padding: t.spacing.sm + 2,
            color: t.colors.text,
            backgroundColor: t.colors.surface,
          },
          style,
        ]}
        {...rest}
      />
    </View>
  );
}
