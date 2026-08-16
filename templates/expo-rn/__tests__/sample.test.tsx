// SAMPLE test — stripped on scaffold. Mobile features are tested with jest +
// @testing-library/react-native (render + fireEvent + getBy*), the way ADF's
// completion audit expects. expo-router's navigation hooks are mocked so a screen
// renders in isolation.
import React from 'react';
import { render, fireEvent } from '@testing-library/react-native';

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: '1' }),
}));

import ItemsScreen from '../app/index';

describe('items list screen', () => {
  it('renders the add form + empty state and accepts input', () => {
    const { getByText, getByPlaceholderText } = render(<ItemsScreen />);
    expect(getByText('Add item')).toBeTruthy();
    expect(getByText('No items yet')).toBeTruthy();
    const input = getByPlaceholderText('Enter a title');
    fireEvent.changeText(input, 'Buy milk');
    expect(input.props.value).toBe('Buy milk');
  });
});
