import React, { useState } from 'react';
import ButtonDropdown from '@cloudscape-design/components/button-dropdown';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import type { PropertyFilterProps } from '@cloudscape-design/components/property-filter';
import { usePreferences } from '@/context/PreferencesContext';

interface SavedFiltersDropdownProps {
  entity: string;
  currentQuery: PropertyFilterProps.Query;
  onApply: (query: PropertyFilterProps.Query) => void;
}

const SavedFiltersDropdown: React.FC<SavedFiltersDropdownProps> = ({
  entity,
  currentQuery,
  onApply,
}) => {
  const { getSavedFilters, addSavedFilter, removeSavedFilter } = usePreferences();
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [filterName, setFilterName] = useState('');

  const savedFilters = getSavedFilters(entity);

  const handleSave = () => {
    if (!filterName.trim()) return;
    addSavedFilter(entity, {
      name: filterName.trim(),
      tokens: currentQuery.tokens.map((t) => {
        if ('propertyKey' in t) {
          return { propertyKey: t.propertyKey, operator: t.operator, value: t.value };
        }
        return { value: t.value };
      }),
      operation: currentQuery.operation,
    });
    setFilterName('');
    setSaveModalOpen(false);
  };

  const handleApply = (name: string) => {
    const filter = savedFilters.find((f) => f.name === name);
    if (filter) {
      onApply({
        tokens: filter.tokens.map((t) => {
          if (t.propertyKey) {
            return {
              propertyKey: t.propertyKey,
              operator: t.operator ?? '=',
              value: t.value ?? '',
            };
          }
          return { value: t.value ?? '' };
        }) as PropertyFilterProps.Token[],
        operation: filter.operation,
      });
    }
  };

  const hasTokens = currentQuery.tokens.length > 0;

  const items = [
    ...(hasTokens
      ? [{ id: '__save__', text: 'Save current filter...' }]
      : []),
    ...(savedFilters.length > 0 && hasTokens
      ? [{ id: '__divider_1__', text: '-' }]
      : []),
    ...savedFilters.map((f) => ({
      id: f.name,
      text: f.name,
    })),
  ];

  if (items.length === 0) {
    return null;
  }

  return (
    <>
      <ButtonDropdown
        items={items}
        onItemClick={({ detail }) => {
          if (detail.id === '__save__') {
            setSaveModalOpen(true);
          } else if (!detail.id.startsWith('__')) {
            handleApply(detail.id);
          }
        }}
      >
        Saved filters
      </ButtonDropdown>

      <Modal
        visible={saveModalOpen}
        onDismiss={() => setSaveModalOpen(false)}
        header="Save filter"
        closeAriaLabel="Close"
        size="small"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setSaveModalOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleSave} disabled={!filterName.trim()}>Save</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <FormField label="Filter name">
          <Input
            value={filterName}
            onChange={({ detail }) => setFilterName(detail.value)}
            placeholder="e.g., My active offices"
            onKeyDown={({ detail }) => {
              if (detail.key === 'Enter') handleSave();
            }}
          />
        </FormField>
        {savedFilters.length > 0 && (
          <SpaceBetween size="xs">
            <Box variant="h4" margin={{ top: 'm' }}>Existing filters</Box>
            {savedFilters.map((f) => (
              <Box key={f.name}>
                <SpaceBetween direction="horizontal" size="xs">
                  <Box>{f.name}</Box>
                  <Button
                    variant="icon"
                    iconName="close"
                    onClick={() => removeSavedFilter(entity, f.name)}
                    ariaLabel={`Delete filter ${f.name}`}
                  />
                </SpaceBetween>
              </Box>
            ))}
          </SpaceBetween>
        )}
      </Modal>
    </>
  );
};

export default SavedFiltersDropdown;
