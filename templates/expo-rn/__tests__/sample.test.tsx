// SAMPLE test — stripped on scaffold. Mobile features are tested with jest +
// @testing-library/react-native (render + fireEvent + getBy*), the way ADF's
// completion audit expects.
import React from 'react';
import { render, fireEvent } from '@testing-library/react-native';
import { ItemList } from '../src/components/ItemList';

describe('ItemList', () => {
  it('renders the add form with an input and a button', () => {
    const { getByPlaceholderText, getByText } = render(<ItemList />);
    expect(getByPlaceholderText('Enter a title')).toBeTruthy();
    expect(getByText('Add')).toBeTruthy();
  });

  it('lets the user type a title', () => {
    const { getByPlaceholderText } = render(<ItemList />);
    const input = getByPlaceholderText('Enter a title');
    fireEvent.changeText(input, 'Milk');
    expect(input.props.value).toBe('Milk');
  });
});
