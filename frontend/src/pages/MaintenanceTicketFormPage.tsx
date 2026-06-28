import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Textarea from '@cloudscape-design/components/textarea';
import RadioGroup from '@cloudscape-design/components/radio-group';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import {
  maintenanceTickets as ticketsApi,
  offices as officesApi,
  ticketCategories as categoriesApi,
  managers as managersApi,
  vendors as vendorsApi,
  attachments as attachmentsApi,
  ticketTemplates as templatesApi,
  ai as aiApi,
} from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import { EntityQuickCreateSelect } from '@/components/common/EntityQuickCreateSelect';
import AITicketAssist from '@/components/common/AITicketAssist';
import {
  OfficeQuickCreate,
  ManagerQuickCreate,
  TicketCategoryQuickCreate,
} from '@/components/common/QuickCreateForms';
import type { Office, TicketCategory, Manager, TicketTemplate, Vendor, TicketTriageSuggestion } from '@/types';

type SelectOption = { label: string; value: string };

const MaintenanceTicketFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEditing = !!id;

  const [loading, setLoading] = useState(isEditing);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);
  const [categoryOptions, setCategoryOptions] = useState<SelectOption[]>([]);
  const [managerOptions, setManagerOptions] = useState<SelectOption[]>([]);
  const [vendorOptions, setVendorOptions] = useState<SelectOption[]>([]);

  const [subject, setSubject] = useState('');
  const [priority, setPriority] = useState('low');
  const [status, setStatus] = useState('open');
  const [locationHours, setLocationHours] = useState('');
  const [description, setDescription] = useState('');
  const [scheduledDate, setScheduledDate] = useState('');
  const [estimatedDuration, setEstimatedDuration] = useState('');
  const [actualStart, setActualStart] = useState('');
  const [actualEnd, setActualEnd] = useState('');
  const [technicianName, setTechnicianName] = useState('');

  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);

  const [selectedOffice, setSelectedOffice] = useState<SelectOption | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<SelectOption | null>(null);
  const [selectedAssignedTo, setSelectedAssignedTo] = useState<SelectOption | null>(null);
  const [selectedVendor, setSelectedVendor] = useState<SelectOption | null>(null);

  const [templates, setTemplates] = useState<TicketTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<SelectOption | null>(null);
  const [pendingVendorId, setPendingVendorId] = useState<string | null>(null);

  // AI triage assist
  const [aiConfigured, setAiConfigured] = useState(false);
  const [triaging, setTriaging] = useState(false);
  const [triageError, setTriageError] = useState<string | null>(null);
  const [triageInfo, setTriageInfo] = useState<string | null>(null);

  // Load dropdown options
  useEffect(() => {
    const loadOptions = async () => {
      try {
        const [offRes, catRes, mgrRes, tRes] = await Promise.all([
          officesApi.list({ page_size: 1000 }),
          categoriesApi.list(),
          managersApi.list(),
          templatesApi.list(),
        ]);
        setOfficeOptions(
          offRes.data.items.map((o: Office) => ({
            label: `${o.office_number} - ${o.location_name}`,
            value: String(o.id),
          }))
        );
        setCategoryOptions(
          (Array.isArray(catRes.data) ? catRes.data : []).map((c: TicketCategory) => ({
            label: c.name,
            value: String(c.id),
          }))
        );
        setManagerOptions(
          (Array.isArray(mgrRes.data) ? mgrRes.data : []).map((m: Manager) => ({
            label: m.name,
            value: String(m.id),
          }))
        );
        setTemplates(Array.isArray(tRes.data) ? tRes.data : []);
        try {
          const venRes = await vendorsApi.list({ page_size: 1000 });
          setVendorOptions(
            (venRes.data.items ?? []).map((v: Vendor) => ({
              label: v.company_name,
              value: String(v.id),
            }))
          );
        } catch {
          // vendors are optional; ignore load failures
        }
      } catch {
        // non-critical
      }
    };
    loadOptions();
  }, []);

  // Load existing ticket when editing
  useEffect(() => {
    if (!isEditing || !id) return;
    const fetchTicket = async () => {
      try {
        const res = await ticketsApi.get(id);
        const t = res.data;
        setSubject(t.subject);
        setPriority(t.priority);
        setStatus(t.status);
        setLocationHours(t.location_hours || '');
        setDescription(t.description);
        setScheduledDate(t.scheduled_date ? t.scheduled_date.slice(0, 16) : '');
        setEstimatedDuration(t.estimated_duration_minutes != null ? String(t.estimated_duration_minutes) : '');
        setActualStart(t.actual_start_at ? t.actual_start_at.slice(0, 16) : '');
        setActualEnd(t.actual_end_at ? t.actual_end_at.slice(0, 16) : '');
        setTechnicianName(t.technician_name || '');
        if (t.office) {
          setSelectedOffice({
            label: `${t.office.office_number} - ${t.office.location_name}`,
            value: String(t.office.id),
          });
        }
        if (t.category) {
          setSelectedCategory({ label: t.category.name, value: String(t.category.id) });
        }
        if (t.assigned_to) {
          setSelectedAssignedTo({ label: t.assigned_to.name, value: String(t.assigned_to.id) });
        }
        if (t.vendor_id) {
          setPendingVendorId(String(t.vendor_id));
        }
      } catch {
        setError('Failed to load ticket data.');
      } finally {
        setLoading(false);
      }
    };
    fetchTicket();
  }, [id, isEditing]);

  // Resolve the assigned vendor's label once the vendor options have loaded.
  useEffect(() => {
    if (!pendingVendorId) return;
    const match = vendorOptions.find((o) => o.value === pendingVendorId);
    if (match) {
      setSelectedVendor(match);
      setPendingVendorId(null);
    }
  }, [pendingVendorId, vendorOptions]);

  // Detect whether AI assist is configured so the triage action can be shown.
  useEffect(() => {
    aiApi
      .status()
      .then((res) => setAiConfigured(!!res.data.configured))
      .catch(() => setAiConfigured(false));
  }, []);

  const runTriage = async () => {
    if (!subject.trim() && !description.trim()) {
      setTriageError('Add a subject or description first.');
      return;
    }
    setTriaging(true);
    setTriageError(null);
    setTriageInfo(null);
    try {
      const res = await aiApi.triageTicket(subject.trim(), description.trim());
      const s = res.data.suggested || {};
      const applied: string[] = [];

      const suggestedPriority = (s.priority || '').toLowerCase();
      if (['low', 'medium', 'high'].includes(suggestedPriority)) {
        setPriority(suggestedPriority);
        applied.push(`priority "${suggestedPriority}"`);
      }
      if (s.category_id) {
        const match = categoryOptions.find((o) => o.value === String(s.category_id));
        if (match) {
          setSelectedCategory(match);
          applied.push(`category "${match.label}"`);
        }
      }
      if (s.vendor_id) {
        const match = vendorOptions.find((o) => o.value === String(s.vendor_id));
        if (match) {
          setSelectedVendor(match);
          applied.push(`vendor "${match.label}"`);
        }
      }

      const infoParts: string[] = [];
      if (applied.length > 0) {
        infoParts.push(`Applied ${applied.join(', ')}.`);
      } else {
        infoParts.push('No confident match — please set the fields manually.');
      }
      if (s.reasoning) infoParts.push(String(s.reasoning));
      if (s.draft_response) infoParts.push(`Suggested reply: ${String(s.draft_response)}`);
      setTriageInfo(infoParts.join(' '));
    } catch (err: unknown) {
      const code = (err as { response?: { status?: number } })?.response?.status;
      if (code === 503) {
        setTriageError('AI assist is not configured on the server.');
      } else if (code === 402) {
        setTriageError('AI triage is available on the Pro plan and above.');
      } else {
        setTriageError('Could not generate suggestions. Please set the fields manually.');
      }
    } finally {
      setTriaging(false);
    }
  };

  const applyTriage = (s: TicketTriageSuggestion) => {
    if (s.priority && ['low', 'medium', 'high'].includes(s.priority)) {
      setPriority(s.priority);
    }
    if (s.category_id && s.category_name) {
      setSelectedCategory({ label: s.category_name, value: String(s.category_id) });
    }
    if (s.vendor_id && s.vendor_name) {
      setSelectedVendor({ label: s.vendor_name, value: String(s.vendor_id) });
    }
  };

  const handleSubmit = async () => {
    if (!subject.trim()) {
      setError('Subject is required.');
      return;
    }
    if (!selectedCategory) {
      setError('Category is required.');
      return;
    }
    if (!selectedOffice) {
      setError('Location is required.');
      return;
    }
    if (!description.trim()) {
      setError('Description is required.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = {
        subject: subject.trim(),
        priority,
        status,
        category_id: selectedCategory.value,
        office_id: selectedOffice.value,
        location_hours: locationHours.trim() || undefined,
        description: description.trim(),
        assigned_to_id: selectedAssignedTo?.value || undefined,
        vendor_id: selectedVendor?.value || undefined,
        scheduled_date: scheduledDate || undefined,
        estimated_duration_minutes: estimatedDuration ? parseInt(estimatedDuration, 10) : undefined,
        actual_start_at: actualStart || undefined,
        actual_end_at: actualEnd || undefined,
        technician_name: technicianName.trim() || undefined,
      };

      if (isEditing && id) {
        await ticketsApi.update(id, payload);
        navigate(`/maintenance-tickets/${id}`);
      } else {
        const res = await ticketsApi.create(payload);
        const newId = String(res.data.id);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('maintenance_ticket', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        if (failed.length > 0) {
          setError(
            `Ticket created, but ${failed.length} attachment(s) failed: ${failed.join(', ')}. Re-upload from the ticket page.`,
          );
        }
        navigate(`/maintenance-tickets/${newId}`);
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        `Failed to ${isEditing ? 'update' : 'create'} ticket.`;
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Maintenance Tickets', href: '/maintenance-tickets' },
              isEditing
                ? { text: 'Edit Ticket', href: `/maintenance-tickets/${id}/edit` }
                : { text: 'New Ticket', href: '/maintenance-tickets/new' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header variant="h1">
            {isEditing ? 'Edit Maintenance Ticket' : 'New Maintenance Ticket'}
          </Header>
        </SpaceBetween>
      }
    >
      {error && (
        <Alert type="error" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button
              onClick={() =>
                navigate(isEditing ? `/maintenance-tickets/${id}` : '/maintenance-tickets')
              }
            >
              Cancel
            </Button>
            <Button variant="primary" loading={saving} onClick={handleSubmit}>
              {isEditing ? 'Save Changes' : 'Create Ticket'}
            </Button>
          </SpaceBetween>
        }
      >
        <Container header={<Header variant="h2">Ticket Information</Header>}>
          <SpaceBetween size="l">
            {!isEditing && templates.length > 0 && (
              <FormField
                label="Load Template"
                description="Pre-fill this form from a saved template (optional)"
              >
                <Select
                  selectedOption={selectedTemplate}
                  onChange={({ detail }) => {
                    const opt = detail.selectedOption as SelectOption;
                    setSelectedTemplate(opt);
                    const tmpl = templates.find((t) => String(t.id) === opt.value);
                    if (!tmpl) return;
                    setSubject(tmpl.subject);
                    setDescription(tmpl.description ?? '');
                    setPriority(tmpl.priority);
                    if (tmpl.category) {
                      setSelectedCategory({ label: tmpl.category.name, value: String(tmpl.category.id) });
                    } else {
                      setSelectedCategory(null);
                    }
                    if (tmpl.office) {
                      setSelectedOffice({
                        label: `${tmpl.office.office_number} - ${tmpl.office.location_name}`,
                        value: String(tmpl.office.id),
                      });
                    } else {
                      setSelectedOffice(null);
                    }
                    if (tmpl.assigned_to) {
                      setSelectedAssignedTo({ label: tmpl.assigned_to.name, value: String(tmpl.assigned_to.id) });
                    } else {
                      setSelectedAssignedTo(null);
                    }
                  }}
                  options={templates.map((t) => ({ label: t.name, value: String(t.id) }))}
                  placeholder="Select a template to pre-fill"
                  filteringType="auto"
                  disabled={saving}
                />
              </FormField>
            )}

            <FormField label="Subject" constraintText="Required">
              <Input
                value={subject}
                onChange={({ detail }) => setSubject(detail.value)}
                placeholder="Brief summary of the issue"
                disabled={saving}
              />
            </FormField>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Priority" constraintText="Required" stretch>
                <RadioGroup
                  value={priority}
                  onChange={({ detail }) => setPriority(detail.value)}
                  items={[
                    { value: 'low', label: 'Low' },
                    { value: 'medium', label: 'Medium' },
                    { value: 'high', label: 'High' },
                  ]}
                />
              </FormField>
              <FormField label="Status" stretch>
                <RadioGroup
                  value={status}
                  onChange={({ detail }) => setStatus(detail.value)}
                  items={[
                    { value: 'open', label: 'Open' },
                    { value: 'in_progress', label: 'In Progress' },
                    { value: 'closed', label: 'Closed' },
                  ]}
                />
              </FormField>
            </SpaceBetween>

            <FormField label="Category" constraintText="Required">
              <EntityQuickCreateSelect
                selectedOption={selectedCategory}
                onChange={(opt) => setSelectedCategory(opt)}
                options={categoryOptions}
                placeholder="Select category"
                disabled={saving}
                quickCreate={{
                  label: '+ Add new category…',
                  render: ({ visible, onClose, onCreated }) => (
                    <TicketCategoryQuickCreate
                      visible={visible}
                      onClose={onClose}
                      onCreated={onCreated}
                    />
                  ),
                }}
              />
            </FormField>

            <FormField label="Location" constraintText="Required">
              <EntityQuickCreateSelect
                selectedOption={selectedOffice}
                onChange={(opt) => setSelectedOffice(opt)}
                options={officeOptions}
                placeholder="Select office location"
                disabled={saving}
                quickCreate={{
                  label: '+ Add new office…',
                  render: ({ visible, onClose, onCreated }) => (
                    <OfficeQuickCreate visible={visible} onClose={onClose} onCreated={onCreated} />
                  ),
                }}
              />
            </FormField>

            <FormField label="Office Location and Hours/Schedule">
              <Input
                value={locationHours}
                onChange={({ detail }) => setLocationHours(detail.value)}
                placeholder="e.g., Mon-Fri 8am-5pm"
                disabled={saving}
              />
            </FormField>

            <FormField label="Description" constraintText="Required">
              <Textarea
                value={description}
                onChange={({ detail }) => setDescription(detail.value)}
                placeholder="Detailed description of the maintenance issue..."
                rows={6}
                disabled={saving}
              />
            </FormField>

            {!isEditing && aiConfigured && (
              <SpaceBetween size="xs">
                <Button
                  iconName="gen-ai"
                  onClick={runTriage}
                  loading={triaging}
                  disabled={saving}
                >
                  Suggest category, priority &amp; vendor with AI
                </Button>
                {triageError && (
                  <Alert type="warning" dismissible onDismiss={() => setTriageError(null)}>
                    {triageError}
                  </Alert>
                )}
                {triageInfo && !triageError && (
                  <Alert type="success" dismissible onDismiss={() => setTriageInfo(null)}>
                    {triageInfo}
                  </Alert>
                )}
              </SpaceBetween>
            )}

            <AITicketAssist
              subject={subject}
              description={description}
              excludeId={isEditing && id ? id : undefined}
              onApply={applyTriage}
            />

            <FormField label="Assigned To">
              <EntityQuickCreateSelect
                selectedOption={selectedAssignedTo}
                onChange={(opt) => setSelectedAssignedTo(opt)}
                options={managerOptions}
                placeholder="Select manager (optional)"
                disabled={saving}
                quickCreate={{
                  label: '+ Add new manager…',
                  render: ({ visible, onClose, onCreated }) => (
                    <ManagerQuickCreate visible={visible} onClose={onClose} onCreated={onCreated} />
                  ),
                }}
              />
            </FormField>

            <FormField
              label="Vendor"
              description="Assign an external vendor to perform this work (optional)"
            >
              <Select
                selectedOption={selectedVendor}
                onChange={({ detail }) =>
                  setSelectedVendor((detail.selectedOption as SelectOption) ?? null)
                }
                options={vendorOptions}
                placeholder="Select vendor"
                filteringType="auto"
                disabled={saving}
                empty="No vendors available"
              />
            </FormField>

            <FormField label="Scheduled Date" description="When this work is scheduled to occur">
              <Input
                type="datetime-local"
                value={scheduledDate}
                onChange={({ detail }) => setScheduledDate(detail.value)}
                disabled={saving}
              />
            </FormField>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Estimated Duration (minutes)" stretch>
                <Input
                  type="number"
                  value={estimatedDuration}
                  onChange={({ detail }) => setEstimatedDuration(detail.value)}
                  placeholder="e.g. 120"
                  disabled={saving}
                />
              </FormField>
              <FormField label="Technician Name" stretch>
                <Input
                  value={technicianName}
                  onChange={({ detail }) => setTechnicianName(detail.value)}
                  placeholder="Name of assigned technician"
                  disabled={saving}
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Actual Start" stretch>
                <Input
                  type="datetime-local"
                  value={actualStart}
                  onChange={({ detail }) => setActualStart(detail.value)}
                  disabled={saving}
                />
              </FormField>
              <FormField label="Actual End" stretch>
                <Input
                  type="datetime-local"
                  value={actualEnd}
                  onChange={({ detail }) => setActualEnd(detail.value)}
                  disabled={saving}
                />
              </FormField>
            </SpaceBetween>

            {!isEditing && (
              <FileQueueField files={queuedFiles} onChange={setQueuedFiles} disabled={saving} />
            )}
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
};

export default MaintenanceTicketFormPage;
