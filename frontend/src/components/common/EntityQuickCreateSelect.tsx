import React, { useMemo, useState } from 'react';
import Select from '@cloudscape-design/components/select';
import Multiselect from '@cloudscape-design/components/multiselect';
import type { QuickCreateOption } from './QuickCreateForms';

/** Sentinel value for the injected "Add new" option. */
const ADD_NEW_VALUE = '__quick_create_add_new__';

export interface QuickCreateConfig {
  /** Label for the injected option. Defaults to "+ Add new…". */
  label?: string;
  /**
   * Renders the create modal. The wrapper supplies `visible`, an `onClose`
   * handler, and an `onCreated` callback that receives the new option (the
   * wrapper then selects it and merges it into the option list).
   */
  render: (args: {
    visible: boolean;
    onClose: () => void;
    onCreated: (option: QuickCreateOption) => void;
  }) => React.ReactNode;
}

function addNewOption(label?: string): QuickCreateOption {
  return { label: label ?? '+ Add new…', value: ADD_NEW_VALUE };
}

/** Merge locally-created options with the provided ones, de-duping by value. */
function mergeOptions(
  base: QuickCreateOption[],
  extra: QuickCreateOption[],
): QuickCreateOption[] {
  const seen = new Set(base.map((o) => o.value));
  const merged = [...base];
  for (const o of extra) {
    if (!seen.has(o.value)) {
      merged.push(o);
      seen.add(o.value);
    }
  }
  return merged;
}

interface BaseProps {
  options: QuickCreateOption[];
  /** When provided, an "Add new" option is injected and inline creation is enabled. */
  quickCreate?: QuickCreateConfig;
  placeholder?: string;
  disabled?: boolean;
  filteringType?: 'auto' | 'none' | 'manual';
  empty?: React.ReactNode;
}

interface SingleProps extends BaseProps {
  selectedOption: QuickCreateOption | null;
  onChange: (option: QuickCreateOption | null) => void;
}

/**
 * A Cloudscape Select that can offer an inline "Add new" option. Selecting it
 * opens a modal (provided by `quickCreate.render`); on save the new record is
 * auto-selected without leaving the page.
 */
export const EntityQuickCreateSelect: React.FC<SingleProps> = ({
  options,
  quickCreate,
  selectedOption,
  onChange,
  placeholder,
  disabled,
  filteringType = 'auto',
  empty,
}) => {
  const [modalVisible, setModalVisible] = useState(false);
  const [extraOptions, setExtraOptions] = useState<QuickCreateOption[]>([]);

  const displayedOptions = useMemo(() => {
    const merged = mergeOptions(options, extraOptions);
    return quickCreate ? [addNewOption(quickCreate.label), ...merged] : merged;
  }, [options, extraOptions, quickCreate]);

  const handleCreated = (option: QuickCreateOption) => {
    setExtraOptions((prev) => mergeOptions(prev, [option]));
    onChange(option);
  };

  return (
    <>
      <Select
        selectedOption={selectedOption}
        onChange={({ detail }) => {
          if (detail.selectedOption?.value === ADD_NEW_VALUE) {
            setModalVisible(true);
            return;
          }
          onChange((detail.selectedOption as QuickCreateOption) ?? null);
        }}
        options={displayedOptions}
        placeholder={placeholder}
        disabled={disabled}
        filteringType={filteringType}
        empty={empty}
      />
      {quickCreate &&
        quickCreate.render({
          visible: modalVisible,
          onClose: () => setModalVisible(false),
          onCreated: handleCreated,
        })}
    </>
  );
};

interface MultiProps extends BaseProps {
  selectedOptions: QuickCreateOption[];
  onChange: (options: QuickCreateOption[]) => void;
  tokenLimit?: number;
}

/**
 * A Cloudscape Multiselect variant of {@link EntityQuickCreateSelect}. Toggling
 * the injected "Add new" option opens the create modal; the new record is added
 * to the current selection.
 */
export const EntityQuickCreateMultiselect: React.FC<MultiProps> = ({
  options,
  quickCreate,
  selectedOptions,
  onChange,
  placeholder,
  disabled,
  filteringType = 'auto',
  tokenLimit,
  empty,
}) => {
  const [modalVisible, setModalVisible] = useState(false);
  const [extraOptions, setExtraOptions] = useState<QuickCreateOption[]>([]);

  const displayedOptions = useMemo(() => {
    const merged = mergeOptions(options, extraOptions);
    return quickCreate ? [addNewOption(quickCreate.label), ...merged] : merged;
  }, [options, extraOptions, quickCreate]);

  const handleCreated = (option: QuickCreateOption) => {
    setExtraOptions((prev) => mergeOptions(prev, [option]));
    onChange(mergeOptions(selectedOptions, [option]));
  };

  return (
    <>
      <Multiselect
        selectedOptions={selectedOptions}
        onChange={({ detail }) => {
          const picked = (detail.selectedOptions as QuickCreateOption[]) ?? [];
          if (picked.some((o) => o.value === ADD_NEW_VALUE)) {
            setModalVisible(true);
            // Strip the sentinel; never let it become a real selection.
            onChange(picked.filter((o) => o.value !== ADD_NEW_VALUE));
            return;
          }
          onChange(picked);
        }}
        options={displayedOptions}
        placeholder={placeholder}
        disabled={disabled}
        filteringType={filteringType}
        tokenLimit={tokenLimit}
        empty={empty}
      />
      {quickCreate &&
        quickCreate.render({
          visible: modalVisible,
          onClose: () => setModalVisible(false),
          onCreated: handleCreated,
        })}
    </>
  );
};
