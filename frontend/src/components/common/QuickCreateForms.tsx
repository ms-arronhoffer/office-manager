import React, { useState } from 'react';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import { managementCompanies, offices, managers, ticketCategories, selfStorage } from '@/api';
import QuickCreateModal from './QuickCreateModal';

export interface QuickCreateOption {
  label: string;
  value: string;
}

interface EntityModalProps {
  visible: boolean;
  onClose: () => void;
  /** Called with the newly-created record mapped to a select option. */
  onCreated: (option: QuickCreateOption) => void;
}

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

/** Quick-create modal for a Property Management Company (minimal fields). */
export const ManagementCompanyQuickCreate: React.FC<EntityModalProps> = ({
  visible,
  onClose,
  onCreated,
}) => {
  const [name, setName] = useState('');
  const [contactName, setContactName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName('');
    setContactName('');
    setContactEmail('');
    setContactPhone('');
    setError(null);
  };

  const handleCancel = () => {
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await managementCompanies.create({
        name: name.trim(),
        contact_name: contactName.trim() || undefined,
        contact_email: contactEmail.trim() || undefined,
        contact_phone: contactPhone.trim() || undefined,
      });
      onCreated({ label: res.data.name, value: String(res.data.id) });
      reset();
      onClose();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create management company.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <QuickCreateModal
      visible={visible}
      title="New Management Company"
      onSubmit={handleSubmit}
      onCancel={handleCancel}
      submitting={submitting}
      submitDisabled={!name.trim()}
      error={error}
      submitLabel="Create Management Company"
    >
      <FormField label="Company Name" constraintText="Required">
        <Input
          value={name}
          onChange={({ detail }) => setName(detail.value)}
          placeholder="Enter company name"
        />
      </FormField>
      <FormField label="Contact Name">
        <Input
          value={contactName}
          onChange={({ detail }) => setContactName(detail.value)}
          placeholder="Primary contact"
        />
      </FormField>
      <FormField label="Email">
        <Input
          value={contactEmail}
          onChange={({ detail }) => setContactEmail(detail.value)}
          type="email"
          placeholder="Email address"
        />
      </FormField>
      <FormField label="Phone">
        <Input
          value={contactPhone}
          onChange={({ detail }) => setContactPhone(detail.value)}
          placeholder="Phone number"
        />
      </FormField>
    </QuickCreateModal>
  );
};

const OFFICE_TYPE_OPTIONS: QuickCreateOption[] = [
  { label: 'Branch', value: 'Branch' },
  { label: 'Headquarters', value: 'Headquarters' },
  { label: 'HQ', value: 'HQ' },
  { label: 'Satellite', value: 'Satellite' },
  { label: 'Remote', value: 'Remote' },
  { label: 'Field', value: 'Field' },
  { label: 'Office', value: 'Office' },
  { label: 'Other', value: 'Other' },
];

/** Quick-create modal for an Office (minimal required fields). */
export const OfficeQuickCreate: React.FC<EntityModalProps> = ({ visible, onClose, onCreated }) => {
  const [officeNumber, setOfficeNumber] = useState('');
  const [locationName, setLocationName] = useState('');
  const [locationType, setLocationType] = useState<QuickCreateOption | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setOfficeNumber('');
    setLocationName('');
    setLocationType(null);
    setError(null);
  };

  const handleCancel = () => {
    reset();
    onClose();
  };

  const valid =
    officeNumber.trim() !== '' &&
    !Number.isNaN(parseInt(officeNumber, 10)) &&
    locationName.trim() !== '' &&
    Boolean(locationType);

  const handleSubmit = async () => {
    if (!valid || !locationType) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await offices.create({
        office_number: parseInt(officeNumber, 10),
        location_name: locationName.trim(),
        location_type: locationType.value,
      });
      onCreated({
        label: `${res.data.office_number} - ${res.data.location_name}`,
        value: String(res.data.id),
      });
      reset();
      onClose();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create office.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <QuickCreateModal
      visible={visible}
      title="New Office"
      onSubmit={handleSubmit}
      onCancel={handleCancel}
      submitting={submitting}
      submitDisabled={!valid}
      error={error}
      submitLabel="Create Office"
    >
      <FormField label="Office Number" constraintText="Required">
        <Input
          value={officeNumber}
          onChange={({ detail }) => setOfficeNumber(detail.value)}
          type="number"
          placeholder="e.g., 101"
        />
      </FormField>
      <FormField label="Location Name" constraintText="Required">
        <Input
          value={locationName}
          onChange={({ detail }) => setLocationName(detail.value)}
          placeholder="e.g., Downtown Branch"
        />
      </FormField>
      <FormField label="Office Type" constraintText="Required">
        <Select
          selectedOption={locationType}
          onChange={({ detail }) => setLocationType(detail.selectedOption as QuickCreateOption)}
          options={OFFICE_TYPE_OPTIONS}
          placeholder="Select type"
        />
      </FormField>
    </QuickCreateModal>
  );
};

/** Quick-create modal for a Manager (minimal fields). */
export const ManagerQuickCreate: React.FC<EntityModalProps> = ({ visible, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName('');
    setEmail('');
    setPhone('');
    setError(null);
  };

  const handleCancel = () => {
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await managers.create({
        name: name.trim(),
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
      });
      onCreated({ label: res.data.name, value: String(res.data.id) });
      reset();
      onClose();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create manager.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <QuickCreateModal
      visible={visible}
      title="New Manager"
      onSubmit={handleSubmit}
      onCancel={handleCancel}
      submitting={submitting}
      submitDisabled={!name.trim()}
      error={error}
      submitLabel="Create Manager"
    >
      <FormField label="Name" constraintText="Required">
        <Input
          value={name}
          onChange={({ detail }) => setName(detail.value)}
          placeholder="Manager name"
        />
      </FormField>
      <FormField label="Email">
        <Input
          value={email}
          onChange={({ detail }) => setEmail(detail.value)}
          type="email"
          placeholder="Email address"
        />
      </FormField>
      <FormField label="Phone">
        <Input
          value={phone}
          onChange={({ detail }) => setPhone(detail.value)}
          placeholder="Phone number"
        />
      </FormField>
    </QuickCreateModal>
  );
};

/** Quick-create modal for a Ticket Category (single field). */
export const TicketCategoryQuickCreate: React.FC<EntityModalProps> = ({
  visible,
  onClose,
  onCreated,
}) => {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName('');
    setError(null);
  };

  const handleCancel = () => {
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await ticketCategories.create({ name: name.trim() });
      onCreated({ label: res.data.name, value: String(res.data.id) });
      reset();
      onClose();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create category.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <QuickCreateModal
      visible={visible}
      title="New Category"
      onSubmit={handleSubmit}
      onCancel={handleCancel}
      submitting={submitting}
      submitDisabled={!name.trim()}
      error={error}
      submitLabel="Create Category"
    >
      <FormField label="Category Name" constraintText="Required">
        <Input
          value={name}
          onChange={({ detail }) => setName(detail.value)}
          placeholder="e.g., Plumbing"
        />
      </FormField>
    </QuickCreateModal>
  );
};

/**
 * Quick-create modal for a self-storage Manager. Mirrors ManagerQuickCreate but
 * targets the self-storage manager data set so the category stands on its own.
 */
export const StorageManagerQuickCreate: React.FC<EntityModalProps> = ({
  visible,
  onClose,
  onCreated,
}) => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName('');
    setEmail('');
    setPhone('');
    setError(null);
  };

  const handleCancel = () => {
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await selfStorage.createManager({
        name: name.trim(),
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
      });
      onCreated({ label: res.data.name, value: String(res.data.id) });
      reset();
      onClose();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create manager.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <QuickCreateModal
      visible={visible}
      title="New Manager"
      onSubmit={handleSubmit}
      onCancel={handleCancel}
      submitting={submitting}
      submitDisabled={!name.trim()}
      error={error}
      submitLabel="Create Manager"
    >
      <FormField label="Name" constraintText="Required">
        <Input
          value={name}
          onChange={({ detail }) => setName(detail.value)}
          placeholder="Manager name"
        />
      </FormField>
      <FormField label="Email">
        <Input
          value={email}
          onChange={({ detail }) => setEmail(detail.value)}
          type="email"
          placeholder="Email address"
        />
      </FormField>
      <FormField label="Phone">
        <Input
          value={phone}
          onChange={({ detail }) => setPhone(detail.value)}
          placeholder="Phone number"
        />
      </FormField>
    </QuickCreateModal>
  );
};
