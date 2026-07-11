// Verifies the shipped design system: tokens resolve light/dark, and the themed
// kit renders. Kept on scaffold (a regression guard the generated feature inherits).
import React from 'react';
import { render } from '@testing-library/react-native';
import { themeFor, lightTheme, darkTheme } from '../src/theme';
import { Screen, Button, Text, Card, Input } from '../src/components/ui';

describe('theme', () => {
  it('themeFor resolves light and dark and they differ', () => {
    expect(themeFor('light')).toBe(lightTheme);
    expect(themeFor('dark')).toBe(darkTheme);
    expect(themeFor(null)).toBe(lightTheme);
    expect(lightTheme.colors.bg).not.toBe(darkTheme.colors.bg);
    expect(lightTheme.colors.primary).not.toBe(darkTheme.colors.primary);
  });

  it('the themed kit renders without crashing', () => {
    const { getByText, getByPlaceholderText } = render(
      <Screen>
        <Text variant="h1">Title</Text>
        <Card title="Card">
          <Input label="Name" placeholder="type here" />
          <Button title="Go" onPress={() => {}} />
        </Card>
      </Screen>
    );
    expect(getByText('Title')).toBeTruthy();
    expect(getByText('Go')).toBeTruthy();
    expect(getByPlaceholderText('type here')).toBeTruthy();
  });
});
