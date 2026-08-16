// MM2: the native component kit renders and exposes real, detectable controls.
import React from 'react';
import { render, fireEvent } from '@testing-library/react-native';
import { Screen, Header, ListItem, Badge, EmptyState, Icon } from '../src/components/ui';

describe('component kit', () => {
  it('Header renders the title and fires actions', () => {
    const onBack = jest.fn();
    const { getByText, getByLabelText } = render(
      <Header title="Inbox" onBack={onBack} />
    );
    expect(getByText('Inbox')).toBeTruthy();
    fireEvent.press(getByLabelText('Back'));
    expect(onBack).toHaveBeenCalled();
  });

  it('ListItem is pressable and shows subtitle', () => {
    const onPress = jest.fn();
    const { getByText } = render(
      <ListItem title="Row" subtitle="detail" onPress={onPress} showChevron />
    );
    expect(getByText('Row')).toBeTruthy();
    expect(getByText('detail')).toBeTruthy();
    fireEvent.press(getByText('Row'));
    expect(onPress).toHaveBeenCalled();
  });

  it('Badge and EmptyState render', () => {
    const { getByText } = render(
      <Screen>
        <Badge label={3} tone="danger" />
        <EmptyState title="Nothing here" message="Add your first item" />
        <Icon name="add" accessibilityLabel="add" />
      </Screen>
    );
    expect(getByText('3')).toBeTruthy();
    expect(getByText('Nothing here')).toBeTruthy();
  });
});
