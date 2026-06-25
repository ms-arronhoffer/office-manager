import React from 'react';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';

export interface StructuredAddress {
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
}

interface AddressFieldsProps {
  value: StructuredAddress;
  onChange: (next: StructuredAddress) => void;
  disabled?: boolean;
  /** Optional legacy free-form address. If supplied and structured fields
   *  are empty, a banner is shown allowing the user to copy it into the
   *  structured fields via best-effort parsing. */
  legacyAddress?: string;
  /** If true, hide the legacy banner even when legacyAddress is set. */
  hideLegacy?: boolean;
}

// Same regex/anchor logic as the backend migration parser so users get
// consistent results when migrating a single record manually.
const STATE_ZIP_RE = /\b([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$/;

export function parseUsAddress(raw: string | undefined | null): StructuredAddress {
  if (!raw) return {};
  let text = raw.replace(/\r/g, '').replace(/\n/g, ', ').trim();
  text = text.replace(/\s+/g, ' ');
  text = text.replace(/,\s*,+/g, ',').replace(/^[,\s]+|[,\s]+$/g, '');

  let state: string | undefined;
  let zip: string | undefined;
  const m = STATE_ZIP_RE.exec(text);
  if (m) {
    state = m[1];
    zip = m[2];
    text = text.slice(0, m.index).replace(/[,\s]+$/, '');
  }

  const parts = text.split(',').map((p) => p.trim()).filter(Boolean);
  let line1: string | undefined;
  let line2: string | undefined;
  let city: string | undefined;

  if (state && parts.length > 0) {
    city = parts.pop();
  }
  if (parts.length > 0) {
    line1 = parts.shift();
  }
  if (parts.length > 0) {
    line2 = parts.join(', ') || undefined;
  }

  return {
    address_line_1: line1?.slice(0, 255),
    address_line_2: line2?.slice(0, 255),
    city: city?.slice(0, 100),
    state: state?.slice(0, 2),
    zip_code: zip?.slice(0, 10),
  };
}

// US state options for the State select.
const US_STATES: { label: string; value: string }[] = [
  ['AL', 'Alabama'], ['AK', 'Alaska'], ['AZ', 'Arizona'], ['AR', 'Arkansas'],
  ['CA', 'California'], ['CO', 'Colorado'], ['CT', 'Connecticut'], ['DE', 'Delaware'],
  ['FL', 'Florida'], ['GA', 'Georgia'], ['HI', 'Hawaii'], ['ID', 'Idaho'],
  ['IL', 'Illinois'], ['IN', 'Indiana'], ['IA', 'Iowa'], ['KS', 'Kansas'],
  ['KY', 'Kentucky'], ['LA', 'Louisiana'], ['ME', 'Maine'], ['MD', 'Maryland'],
  ['MA', 'Massachusetts'], ['MI', 'Michigan'], ['MN', 'Minnesota'], ['MS', 'Mississippi'],
  ['MO', 'Missouri'], ['MT', 'Montana'], ['NE', 'Nebraska'], ['NV', 'Nevada'],
  ['NH', 'New Hampshire'], ['NJ', 'New Jersey'], ['NM', 'New Mexico'], ['NY', 'New York'],
  ['NC', 'North Carolina'], ['ND', 'North Dakota'], ['OH', 'Ohio'], ['OK', 'Oklahoma'],
  ['OR', 'Oregon'], ['PA', 'Pennsylvania'], ['RI', 'Rhode Island'], ['SC', 'South Carolina'],
  ['SD', 'South Dakota'], ['TN', 'Tennessee'], ['TX', 'Texas'], ['UT', 'Utah'],
  ['VT', 'Vermont'], ['VA', 'Virginia'], ['WA', 'Washington'], ['WV', 'West Virginia'],
  ['WI', 'Wisconsin'], ['WY', 'Wyoming'], ['DC', 'District of Columbia'],
].map(([value, label]) => ({ value, label: `${label} (${value})` }));

const ZIP_RE = /^\d{5}(-\d{4})?$/;

const AddressFields: React.FC<AddressFieldsProps> = ({
  value,
  onChange,
  disabled,
  legacyAddress,
  hideLegacy,
}) => {
  const set = (patch: Partial<StructuredAddress>) =>
    onChange({ ...value, ...patch });

  const stateOption = value.state
    ? US_STATES.find((s) => s.value === value.state) ?? { label: value.state, value: value.state }
    : null;

  const isStructuredEmpty =
    !value.address_line_1 && !value.city && !value.state && !value.zip_code;
  const showLegacyBanner =
    !hideLegacy && !!legacyAddress && isStructuredEmpty;

  const zipInvalid =
    value.zip_code !== undefined &&
    value.zip_code !== '' &&
    !ZIP_RE.test(value.zip_code);

  return (
    <SpaceBetween size="m">
      {showLegacyBanner && (
        <Alert
          type="info"
          header="Legacy address on file"
          action={
            <Button
              onClick={() => onChange(parseUsAddress(legacyAddress))}
              disabled={disabled}
            >
              Use this
            </Button>
          }
        >
          <div style={{ whiteSpace: 'pre-wrap' }}>{legacyAddress}</div>
        </Alert>
      )}

      <FormField label="Street Address">
        <Input
          value={value.address_line_1 ?? ''}
          onChange={({ detail }) => set({ address_line_1: detail.value })}
          placeholder="123 Main St"
          disabled={disabled}
        />
      </FormField>

      <FormField label="Address Line 2">
        <Input
          value={value.address_line_2 ?? ''}
          onChange={({ detail }) => set({ address_line_2: detail.value })}
          placeholder="Apt, Suite, Building (optional)"
          disabled={disabled}
        />
      </FormField>

      <SpaceBetween direction="horizontal" size="l">
        <FormField label="City" stretch>
          <Input
            value={value.city ?? ''}
            onChange={({ detail }) => set({ city: detail.value })}
            placeholder="City"
            disabled={disabled}
          />
        </FormField>
        <FormField label="State" stretch>
          <Select
            selectedOption={stateOption}
            onChange={({ detail }) =>
              set({ state: (detail.selectedOption?.value as string) || undefined })
            }
            options={US_STATES}
            placeholder="Select state"
            filteringType="auto"
            disabled={disabled}
            empty="No matching state"
          />
        </FormField>
        <FormField
          label="ZIP Code"
          stretch
          errorText={zipInvalid ? 'Use 5-digit or 5+4 format (e.g. 10001 or 10001-1234).' : undefined}
        >
          <Input
            value={value.zip_code ?? ''}
            onChange={({ detail }) => set({ zip_code: detail.value })}
            placeholder="10001"
            inputMode="numeric"
            disabled={disabled}
          />
        </FormField>
      </SpaceBetween>
    </SpaceBetween>
  );
};

/**
 * Format a structured address for display, falling back to a legacy
 * free-form string when the structured fields are empty.
 */
export function formatAddress(addr: StructuredAddress, legacy?: string): string {
  const parts: string[] = [];
  if (addr.address_line_1) parts.push(addr.address_line_1);
  if (addr.address_line_2) parts.push(addr.address_line_2);
  const cityLine = [addr.city, [addr.state, addr.zip_code].filter(Boolean).join(' ')]
    .filter(Boolean)
    .join(', ');
  if (cityLine) parts.push(cityLine);
  if (parts.length > 0) return parts.join('\n');
  return legacy ?? '';
}

export default AddressFields;
