import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';
import Checkbox from '@cloudscape-design/components/checkbox';
import Badge from '@cloudscape-design/components/badge';
import { useAuth } from '@/auth/AuthContext';
import { offices, ticketCategories, organizations, auth as authApi } from '@/api';

const LOCATION_TYPES = [
  { label: 'Office', value: 'Office' },
  { label: 'Warehouse', value: 'Warehouse' },
  { label: 'Retail', value: 'Retail' },
  { label: 'Remote', value: 'Remote' },
  { label: 'Other', value: 'Other' },
];

const DEFAULT_CATEGORIES = [
  'HVAC',
  'Electrical',
  'Plumbing',
  'General Maintenance',
  'Safety',
  'Cleaning',
  'IT / Network',
  'Security',
];

const STEPS = ['Add your first office', 'Ticket categories', 'Invite your team'];

const OnboardingPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [step, setStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1 — Office
  const [officeNumber, setOfficeNumber] = useState('1');
  const [locationName, setLocationName] = useState('');
  const [locationType, setLocationType] = useState<{ label: string; value: string } | null>(LOCATION_TYPES[0]);

  // Step 2 — Categories
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(
    new Set(DEFAULT_CATEGORIES.slice(0, 5)),
  );
  const [customCategory, setCustomCategory] = useState('');

  // Step 3 — Invite
  const [invites, setInvites] = useState<{ email: string; role: string }[]>([{ email: '', role: 'editor' }]);

  const ROLE_OPTIONS = [
    { label: 'Admin', value: 'admin' },
    { label: 'Editor', value: 'editor' },
    { label: 'Viewer', value: 'viewer' },
  ];

  const toggleCategory = (name: string) => {
    setSelectedCategories(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const addCustomCategory = () => {
    const name = customCategory.trim();
    if (!name) return;
    setSelectedCategories(prev => new Set(prev).add(name));
    setCustomCategory('');
  };

  const addInviteRow = () => {
    setInvites(prev => [...prev, { email: '', role: 'editor' }]);
  };

  const updateInvite = (index: number, field: 'email' | 'role', value: string) => {
    setInvites(prev => prev.map((inv, i) => (i === index ? { ...inv, [field]: value } : inv)));
  };

  const removeInvite = (index: number) => {
    setInvites(prev => prev.filter((_, i) => i !== index));
  };

  const handleNext = async () => {
    setError(null);

    if (step === 0) {
      // Validate + create office (optional — user can leave location_name blank to skip)
      if (locationName.trim()) {
        const num = parseInt(officeNumber, 10);
        if (isNaN(num) || num < 1) {
          setError('Office number must be a positive integer.');
          return;
        }
        setIsSubmitting(true);
        try {
          await offices.create({
            office_number: num,
            location_name: locationName.trim(),
            location_type: locationType?.value ?? 'Office',
            is_active: true,
          });
        } catch (err: unknown) {
          const msg =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
            'Could not create office. You can add offices later.';
          setError(msg);
          setIsSubmitting(false);
          return;
        } finally {
          setIsSubmitting(false);
        }
      }
      setStep(1);
      return;
    }

    if (step === 1) {
      // Create selected categories
      if (selectedCategories.size > 0) {
        setIsSubmitting(true);
        try {
          await Promise.all(
            Array.from(selectedCategories).map(name =>
              ticketCategories.create({ name }).catch(() => null),
            ),
          );
        } finally {
          setIsSubmitting(false);
        }
      }
      setStep(2);
      return;
    }

    if (step === 2) {
      // Send invites (best-effort)
      const validInvites = invites.filter(inv => inv.email.trim());
      if (validInvites.length > 0) {
        setIsSubmitting(true);
        try {
          await Promise.all(
            validInvites.map(inv =>
              authApi
                .register({ email: inv.email.trim(), display_name: inv.email.trim(), password: crypto.randomUUID(), role: inv.role })
                .catch(() => null),
            ),
          );
        } finally {
          setIsSubmitting(false);
        }
      }

      // Mark onboarding complete
      if (user?.organization_id) {
        setIsSubmitting(true);
        try {
          await organizations.update(user.organization_id, { onboarding_complete: true });
        } catch {
          // non-fatal
        } finally {
          setIsSubmitting(false);
        }
      }

      navigate('/', { replace: true });
    }
  };

  const stepContent = () => {
    if (step === 0) {
      return (
        <SpaceBetween direction="vertical" size="l">
          <Box variant="p" color="text-body-secondary">
            Add your first office to get started. You can skip this step and add offices later.
          </Box>
          <FormField label="Office number" constraintText="A unique numeric identifier for this location.">
            <Input
              type="number"
              value={officeNumber}
              onChange={({ detail }) => setOfficeNumber(detail.value)}
              disabled={isSubmitting}
            />
          </FormField>
          <FormField label="Location name" constraintText="Leave blank to skip adding an office now.">
            <Input
              value={locationName}
              onChange={({ detail }) => setLocationName(detail.value)}
              placeholder="e.g. New York HQ"
              disabled={isSubmitting}
            />
          </FormField>
          <FormField label="Location type">
            <Select
              selectedOption={locationType}
              onChange={({ detail }) => setLocationType(detail.selectedOption as { label: string; value: string })}
              options={LOCATION_TYPES}
              disabled={isSubmitting}
            />
          </FormField>
        </SpaceBetween>
      );
    }

    if (step === 1) {
      const allCategories = Array.from(
        new Set([...DEFAULT_CATEGORIES, ...Array.from(selectedCategories)]),
      );
      return (
        <SpaceBetween direction="vertical" size="l">
          <Box variant="p" color="text-body-secondary">
            Choose which ticket categories to create. You can add or remove categories later.
          </Box>
          <SpaceBetween direction="vertical" size="xs">
            {allCategories.map(name => (
              <Checkbox
                key={name}
                checked={selectedCategories.has(name)}
                onChange={() => toggleCategory(name)}
                disabled={isSubmitting}
              >
                {name}
              </Checkbox>
            ))}
          </SpaceBetween>
          <FormField label="Add a custom category">
            <SpaceBetween direction="horizontal" size="xs">
              <Input
                value={customCategory}
                onChange={({ detail }) => setCustomCategory(detail.value)}
                placeholder="e.g. Pest Control"
                disabled={isSubmitting}
                onKeyDown={({ detail }) => {
                  if (detail.key === 'Enter') addCustomCategory();
                }}
              />
              <Button onClick={addCustomCategory} disabled={!customCategory.trim() || isSubmitting}>
                Add
              </Button>
            </SpaceBetween>
          </FormField>
          <Box>
            <Badge color="blue">{selectedCategories.size} selected</Badge>
          </Box>
        </SpaceBetween>
      );
    }

    // Step 3 — Invite
    return (
      <SpaceBetween direction="vertical" size="l">
        <Box variant="p" color="text-body-secondary">
          Invite team members to join your organization. They will receive a temporary password they
          can change on first login. You can skip this and manage users later under Settings.
        </Box>
        <SpaceBetween direction="vertical" size="s">
          {invites.map((inv, i) => (
            <SpaceBetween key={i} direction="horizontal" size="xs">
              <FormField label={i === 0 ? 'Email' : ''}>
                <Input
                  type="email"
                  value={inv.email}
                  onChange={({ detail }) => updateInvite(i, 'email', detail.value)}
                  placeholder="colleague@company.com"
                  disabled={isSubmitting}
                />
              </FormField>
              <FormField label={i === 0 ? 'Role' : ''}>
                <Select
                  selectedOption={ROLE_OPTIONS.find(r => r.value === inv.role) ?? ROLE_OPTIONS[1]}
                  onChange={({ detail }) => updateInvite(i, 'role', (detail.selectedOption as { value: string }).value)}
                  options={ROLE_OPTIONS}
                  disabled={isSubmitting}
                />
              </FormField>
              {invites.length > 1 && (
                <Box padding={{ top: i === 0 ? 'xl' : 'xxs' }}>
                  <Button
                    variant="icon"
                    iconName="remove"
                    onClick={() => removeInvite(i)}
                    disabled={isSubmitting}
                    ariaLabel="Remove"
                  />
                </Box>
              )}
            </SpaceBetween>
          ))}
        </SpaceBetween>
        <Button iconName="add-plus" onClick={addInviteRow} disabled={isSubmitting}>
          Add another
        </Button>
      </SpaceBetween>
    );
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#f0f2f5',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '48px 24px',
      }}
    >
      {/* Progress indicator */}
      <Box margin={{ bottom: 'l' }}>
        <SpaceBetween direction="horizontal" size="xs">
          {STEPS.map((label, i) => (
            <Box
              key={i}
              padding={{ horizontal: 'm', vertical: 'xs' }}
            >
              <SpaceBetween direction="horizontal" size="xs">
                <Box
                  display="inline-block"
                  padding={{ horizontal: 's', vertical: 'xxs' }}
                >
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 28,
                      height: 28,
                      borderRadius: '50%',
                      background: i <= step ? '#0972d3' : '#d1d5db',
                      color: '#fff',
                      fontSize: 13,
                      fontWeight: 600,
                      marginRight: 8,
                    }}
                  >
                    {i < step ? '✓' : i + 1}
                  </span>
                  <span
                    style={{
                      fontSize: 14,
                      fontWeight: i === step ? 600 : 400,
                      color: i === step ? '#0972d3' : i < step ? '#16a34a' : '#6b7280',
                    }}
                  >
                    {label}
                  </span>
                </Box>
                {i < STEPS.length - 1 && (
                  <Box display="inline-block" padding={{ horizontal: 'xxs' }}>
                    <span style={{ color: '#d1d5db', fontSize: 18 }}>›</span>
                  </Box>
                )}
              </SpaceBetween>
            </Box>
          ))}
        </SpaceBetween>
      </Box>

      <div style={{ width: '100%', maxWidth: 640 }}>
        <Container
          header={
            <Header
              variant="h2"
              description={`Step ${step + 1} of ${STEPS.length}`}
            >
              {STEPS[step]}
            </Header>
          }
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                {step > 0 && (
                  <Button onClick={() => setStep(s => s - 1)} disabled={isSubmitting}>
                    Back
                  </Button>
                )}
                <Button variant="primary" loading={isSubmitting} onClick={handleNext}>
                  {step === STEPS.length - 1 ? 'Finish setup' : 'Continue'}
                </Button>
                {step < STEPS.length - 1 && (
                  <Button
                    variant="link"
                    onClick={() => setStep(s => s + 1)}
                    disabled={isSubmitting}
                  >
                    Skip
                  </Button>
                )}
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween direction="vertical" size="m">
            {error && (
              <Alert type="error" dismissible onDismiss={() => setError(null)}>
                {error}
              </Alert>
            )}
            {stepContent()}
          </SpaceBetween>
        </Container>
      </div>
    </div>
  );
};

export default OnboardingPage;
