import React, { useCallback, useEffect, useState } from 'react';
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
import { offices, ticketCategories, organizations, users } from '@/api';

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

// Onboarding is the first thing a new customer does, and an accidental refresh
// part-way through used to send them back to step one with their work lost.
// Progress is persisted per organization so the wizard can be resumed.
const progressKey = (orgId: string | undefined) => `onboarding-progress:${orgId ?? 'unknown'}`;

interface PersistedProgress {
  step: number;
  officeNumber: string;
  locationName: string;
  locationType: string;
  selectedCategories: string[];
  invites: { email: string; role: string }[];
  officeCreated: boolean;
}

const loadProgress = (orgId: string | undefined): Partial<PersistedProgress> => {
  try {
    const raw = window.localStorage.getItem(progressKey(orgId));
    return raw ? (JSON.parse(raw) as Partial<PersistedProgress>) : {};
  } catch {
    return {};
  }
};

const OnboardingPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const saved = React.useRef(loadProgress(user?.organization_id)).current;

  const [step, setStep] = useState(saved.step ?? 0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Names of items that failed to create, so the user can see and retry them
  // rather than discovering the gap later when a ticket form is empty.
  const [failedCategories, setFailedCategories] = useState<string[]>([]);
  const [failedInvites, setFailedInvites] = useState<string[]>([]);

  // Step 1 — Office
  const [officeNumber, setOfficeNumber] = useState(saved.officeNumber ?? '1');
  const [locationName, setLocationName] = useState(saved.locationName ?? '');
  const [locationType, setLocationType] = useState<{ label: string; value: string } | null>(
    LOCATION_TYPES.find(t => t.value === saved.locationType) ?? LOCATION_TYPES[0],
  );
  // Prevents a duplicate office if the user steps back and forward again.
  const [officeCreated, setOfficeCreated] = useState(saved.officeCreated ?? false);

  // Step 2 — Categories
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(
    new Set(saved.selectedCategories ?? DEFAULT_CATEGORIES.slice(0, 5)),
  );
  const [customCategory, setCustomCategory] = useState('');

  // Step 3 — Invite
  const [invites, setInvites] = useState<{ email: string; role: string }[]>(
    saved.invites ?? [{ email: '', role: 'editor' }],
  );

  // Persist after every meaningful change so a refresh resumes where we were.
  useEffect(() => {
    const payload: PersistedProgress = {
      step,
      officeNumber,
      locationName,
      locationType: locationType?.value ?? 'Office',
      selectedCategories: Array.from(selectedCategories),
      invites,
      officeCreated,
    };
    try {
      window.localStorage.setItem(progressKey(user?.organization_id), JSON.stringify(payload));
    } catch {
      // A full or unavailable localStorage must not block setup.
    }
  }, [
    step,
    officeNumber,
    locationName,
    locationType,
    selectedCategories,
    invites,
    officeCreated,
    user?.organization_id,
  ]);

  const clearProgress = useCallback(() => {
    try {
      window.localStorage.removeItem(progressKey(user?.organization_id));
    } catch {
      // Nothing to do; the stale entry is harmless.
    }
  }, [user?.organization_id]);

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
      if (locationName.trim() && !officeCreated) {
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
          setOfficeCreated(true);
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
      const created = await createCategories(Array.from(selectedCategories));
      if (created.failed.length > 0) {
        // Do not advance while categories are missing: the ticket forms that
        // depend on them would silently come up empty.
        setError(
          `${created.failed.length} categor${created.failed.length === 1 ? 'y' : 'ies'} could not be created. Fix or remove them, then continue.`,
        );
        return;
      }
      setStep(2);
      return;
    }

    if (step === 2) {
      const validInvites = invites.filter(inv => inv.email.trim());
      if (validInvites.length > 0) {
        const result = await sendInvites(validInvites);
        if (result.failed.length > 0) {
          setError(
            `${result.failed.length} invitation(s) could not be sent. Correct the address or remove the row, then finish.`,
          );
          return;
        }
      }

      // Only claim setup is complete once the steps above actually succeeded.
      if (user?.organization_id) {
        setIsSubmitting(true);
        try {
          await organizations.update(user.organization_id, { onboarding_complete: true });
        } catch (err: unknown) {
          const msg =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
            'Could not save your setup status. Please try again.';
          setError(msg);
          setIsSubmitting(false);
          return;
        } finally {
          setIsSubmitting(false);
        }
      }

      clearProgress();
      navigate('/', { replace: true });
    }
  };

  const createCategories = async (names: string[]) => {
    if (names.length === 0) return { failed: [] as string[] };
    setIsSubmitting(true);
    const failed: string[] = [];
    try {
      await Promise.all(
        names.map(async name => {
          try {
            await ticketCategories.create({ name });
          } catch (err: unknown) {
            // A category that already exists is not a failure worth blocking on.
            const statusCode = (err as { response?: { status?: number } })?.response?.status;
            if (statusCode !== 409) failed.push(name);
          }
        }),
      );
    } finally {
      setIsSubmitting(false);
    }
    setFailedCategories(failed);
    return { failed };
  };

  const sendInvites = async (rows: { email: string; role: string }[]) => {
    setIsSubmitting(true);
    const failed: string[] = [];
    try {
      await Promise.all(
        rows.map(async inv => {
          try {
            await users.create({
              email: inv.email.trim(),
              display_name: inv.email.trim(),
              role: inv.role,
            });
          } catch (err: unknown) {
            const statusCode = (err as { response?: { status?: number } })?.response?.status;
            if (statusCode !== 409) failed.push(inv.email.trim());
          }
        }),
      );
    } finally {
      setIsSubmitting(false);
    }
    setFailedInvites(failed);
    return { failed };
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
                    onClick={() => {
                      setError(null);
                      setStep(s => s + 1);
                    }}
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
            {step === 1 && failedCategories.length > 0 && (
              <Alert
                type="warning"
                header="These categories were not created"
                action={
                  <Button
                    loading={isSubmitting}
                    onClick={() => createCategories(failedCategories)}
                  >
                    Retry
                  </Button>
                }
              >
                {failedCategories.join(', ')}
              </Alert>
            )}
            {step === 2 && failedInvites.length > 0 && (
              <Alert
                type="warning"
                header="These invitations were not sent"
                action={
                  <Button
                    loading={isSubmitting}
                    onClick={() =>
                      sendInvites(
                        invites.filter(inv => failedInvites.includes(inv.email.trim())),
                      )
                    }
                  >
                    Retry
                  </Button>
                }
              >
                {failedInvites.join(', ')}
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
