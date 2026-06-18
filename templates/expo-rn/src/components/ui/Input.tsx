import React from 'react';
import { View, Text, TextInput, StyleSheet, TextInputProps } from 'react-native';

export interface InputProps extends TextInputProps {
  /** Optional field label rendered above the input. */
  label?: string;
}

/** A labelled text field. react-native-web renders `<TextInput>` as a real
 *  `<input>`, so it is detectable by the render gate. */
export function Input({ label, style, ...rest }: InputProps) {
  return (
    <View style={styles.wrap}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput style={[styles.input, style]} placeholderTextColor="#9ca3af" {...rest} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginBottom: 12 },
  label: { marginBottom: 4, color: '#374151', fontWeight: '500' },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 8,
    padding: 10,
    backgroundColor: '#ffffff',
  },
});
