import React, { useEffect, useState, useCallback } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Multiselect from '@cloudscape-design/components/multiselect';
import Toggle from '@cloudscape-design/components/toggle';
import TokenGroup from '@cloudscape-design/components/token-group';
import Alert from '@cloudscape-design/components/alert';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Tabs from '@cloudscape-design/components/tabs';
import Badge from '@cloudscape-design/components/badge';
import Container from '@cloudscape-design/components/container';
import { emailRules as emailRulesApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type { EmailReminderRule, EmailReminderRuleCreate, EmailLog } from '@/types';

interface RuleType {
  value: string;
  label: string;
}

const formatDate = (iso?: string) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
};

const EmailRulesPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [rules, setRules] = useState<EmailReminderRule[]>([]);
  const [ruleTypes, setRuleTypes] = useState<RuleType[]>([]);
  const [logs, setLogs] = useState<EmailLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [modalVisible, setModalVisible] = useState(false);
  const [editingRule, setEditingRule] = useState<EmailReminderRule | null>(null);
  const [formData, setFormData] = useState<EmailReminderRuleCreate>({
    rule_name: '',
    rule_type: '',
    days_before: 30,
    recipient_emails: [],
    recipient_roles: [],
    delivery_mode: 'immediate',
    escalation_offsets: [],
    escalation_recipient_emails: [],
    require_acknowledgement: false,
    is_active: true,
  });
  const [emailInput, setEmailInput] = useState('');
  const [saving, setSaving] = useState(false);

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<EmailReminderRule | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Test-send state
  const [testSendingId, setTestSendingId] = useState<string | null>(null);

  const handleTestSend = async (rule: EmailReminderRule) => {
    setTestSendingId(rule.id);
    try {
      const res = await emailRulesApi.testSend(rule.id);
      const { sent_to, failed, message } = res.data;
      if (message) {
        addFlash({ type: 'info', content: message });
      } else if (failed.length === 0) {
        addFlash({ type: 'success', content: `Test email sent to: ${sent_to.join(', ')}` });
      } else {
        addFlash({ type: 'warning', content: `Sent to: ${sent_to.join(', ') || 'none'}. Failed: ${failed.join(', ')}` });
      }
    } catch {
      addFlash({ type: 'error', content: 'Failed to send test email.' });
    } finally {
      setTestSendingId(null);
    }
  };

  const fetchRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rulesRes, typesRes] = await Promise.all([
        emailRulesApi.list(),
        emailRulesApi.getTypes(),
      ]);
      setRules(rulesRes.data);
      setRuleTypes(typesRes.data);
    } catch {
      setError('Failed to load email rules.');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const res = await emailRulesApi.getLogs(200);
      setLogs(res.data);
    } catch {
      setError('Failed to load email logs.');
    } finally {
      setLogsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  const openCreateModal = () => {
    setEditingRule(null);
    setFormData({
      rule_name: '', rule_type: '', days_before: 30, recipient_emails: [],
      recipient_roles: [], delivery_mode: 'immediate', escalation_offsets: [],
      escalation_recipient_emails: [], require_acknowledgement: false, is_active: true,
    });
    setEmailInput('');
    setModalVisible(true);
  };

  const openEditModal = (rule: EmailReminderRule) => {
    setEditingRule(rule);
    setFormData({
      rule_name: rule.rule_name,
      rule_type: rule.rule_type,
      days_before: rule.days_before,
      recipient_emails: [...rule.recipient_emails],
      recipient_roles: [...(rule.recipient_roles ?? [])],
      delivery_mode: rule.delivery_mode ?? 'immediate',
      escalation_offsets: [...(rule.escalation_offsets ?? [])],
      escalation_recipient_emails: [...(rule.escalation_recipient_emails ?? [])],
      require_acknowledgement: rule.require_acknowledgement ?? false,
      is_active: rule.is_active,
    });
    setEmailInput('');
    setModalVisible(true);
  };

  const handleSave = async () => {
    if (!formData.rule_name.trim() || !formData.rule_type || formData.recipient_emails.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      if (editingRule) {
        await emailRulesApi.update(editingRule.id, formData);
      } else {
        await emailRulesApi.create(formData);
      }
      setModalVisible(false);
      await fetchRules();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to save rule.');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (rule: EmailReminderRule) => {
    try {
      await emailRulesApi.update(rule.id, { is_active: !rule.is_active });
      await fetchRules();
    } catch {
      setError('Failed to update rule.');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await emailRulesApi.delete(deleteTarget.id);
      setDeleteTarget(null);
      await fetchRules();
    } catch {
      setError('Failed to delete rule.');
    } finally {
      setDeleting(false);
    }
  };

  const addEmail = () => {
    const email = emailInput.trim();
    if (email && !formData.recipient_emails.includes(email)) {
      setFormData({ ...formData, recipient_emails: [...formData.recipient_emails, email] });
    }
    setEmailInput('');
  };

  const ruleTypeLabel = (value: string) =>
    ruleTypes.find((t) => t.value === value)?.label ?? value;

  const ruleColumnDefinitions = [
    {
      id: 'rule_name',
      header: 'Rule Name',
      cell: (item: EmailReminderRule) => item.rule_name,
      sortingField: 'rule_name',
    },
    {
      id: 'rule_type',
      header: 'Type',
      cell: (item: EmailReminderRule) => (
        <Badge color="blue">{ruleTypeLabel(item.rule_type)}</Badge>
      ),
      sortingField: 'rule_type',
    },
    {
      id: 'days_before',
      header: 'Days Before',
      cell: (item: EmailReminderRule) =>
        item.rule_type === 'high_priority_ticket'
          ? 'Immediately'
          : item.rule_type === 'ai_briefing'
            ? 'Weekly'
            : item.days_before,
      sortingField: 'days_before',
    },
    {
      id: 'recipients',
      header: 'Recipients',
      cell: (item: EmailReminderRule) => item.recipient_emails.join(', '),
    },
    {
      id: 'is_active',
      header: 'Active',
      cell: (item: EmailReminderRule) => (
        <Toggle
          checked={item.is_active}
          onChange={() => handleToggleActive(item)}
        />
      ),
    },
    {
      id: 'last_triggered',
      header: 'Last Triggered',
      cell: (item: EmailReminderRule) => formatDate(item.last_triggered_at),
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: (item: EmailReminderRule) => (
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="inline-icon" iconName="envelope" ariaLabel="Send Test" title="Send test email" loading={testSendingId === item.id} onClick={() => handleTestSend(item)} />
          <Button variant="inline-icon" iconName="edit" onClick={() => openEditModal(item)} />
          <Button variant="inline-icon" iconName="remove" onClick={() => setDeleteTarget(item)} />
        </SpaceBetween>
      ),
    },
  ];

  const logColumnDefinitions = [
    {
      id: 'sent_at',
      header: 'Sent At',
      cell: (item: EmailLog) => formatDate(item.sent_at),
      sortingField: 'sent_at',
    },
    {
      id: 'sent_to',
      header: 'Recipient',
      cell: (item: EmailLog) => item.sent_to,
    },
    {
      id: 'subject',
      header: 'Subject',
      cell: (item: EmailLog) => item.subject,
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item: EmailLog) => (
        <StatusIndicator type={item.status === 'sent' ? 'success' : item.status === 'failed' ? 'error' : 'info'}>
          {item.status}
        </StatusIndicator>
      ),
    },
  ];

  return (
    <ContentLayout
      header={
        <Header variant="h1" description="Configure automated email reminders for lease expirations, HVAC service, and PM tasks.">
          Email Rules
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Tabs
          tabs={[
            {
              label: 'Rules',
              id: 'rules',
              content: (
                <Table
                  loading={loading}
                  loadingText="Loading rules..."
                  columnDefinitions={ruleColumnDefinitions}
                  items={rules}
                  header={
                    <Header
                      counter={loading ? undefined : `(${rules.length})`}
                      actions={
                        <SpaceBetween direction="horizontal" size="xs">
                          <Button onClick={fetchRules} iconName="refresh" />
                          <Button variant="primary" onClick={openCreateModal}>
                            Create Rule
                          </Button>
                        </SpaceBetween>
                      }
                    >
                      Reminder Rules
                    </Header>
                  }
                  empty={
                    <Box textAlign="center" color="inherit" padding="l">
                      <b>No rules configured.</b>
                      <Box variant="p" padding={{ bottom: 's' }}>
                        Create a rule to start receiving automated email reminders.
                      </Box>
                    </Box>
                  }
                />
              ),
            },
            {
              label: 'Email Log',
              id: 'logs',
              content: (
                <Table
                  loading={logsLoading}
                  loadingText="Loading email logs..."
                  columnDefinitions={logColumnDefinitions}
                  items={logs}
                  header={
                    <Header
                      counter={logsLoading ? undefined : `(${logs.length})`}
                      actions={
                        <Button onClick={fetchLogs} iconName="refresh" />
                      }
                    >
                      Email Send History
                    </Header>
                  }
                  empty={
                    <Box textAlign="center" color="inherit" padding="l">
                      <b>No emails sent yet.</b>
                    </Box>
                  }
                />
              ),
            },
          ]}
          onChange={({ detail }) => {
            if (detail.activeTabId === 'logs' && logs.length === 0) {
              fetchLogs();
            }
          }}
        />

        {/* Create / Edit Modal */}
        <Modal
          visible={modalVisible}
          onDismiss={() => setModalVisible(false)}
          header={editingRule ? 'Edit Rule' : 'Create Rule'}
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => setModalVisible(false)}>Cancel</Button>
                <Button
                  variant="primary"
                  loading={saving}
                  disabled={!formData.rule_name.trim() || !formData.rule_type || formData.recipient_emails.length === 0}
                  onClick={handleSave}
                >
                  {editingRule ? 'Save Changes' : 'Create'}
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="l">
            <FormField label="Rule Name">
              <Input
                value={formData.rule_name}
                onChange={({ detail }) => setFormData({ ...formData, rule_name: detail.value })}
                placeholder="e.g. 90-Day Lease Expiration Warning"
              />
            </FormField>

            <FormField label="Rule Type">
              <Select
                selectedOption={
                  formData.rule_type
                    ? { value: formData.rule_type, label: ruleTypeLabel(formData.rule_type) }
                    : null
                }
                onChange={({ detail }) => {
                  const newType = detail.selectedOption.value ?? '';
                  setFormData({
                    ...formData,
                    rule_type: newType,
                    days_before: newType === 'high_priority_ticket' ? 0 : formData.days_before,
                  });
                }}
                options={ruleTypes.map((t) => ({ value: t.value, label: t.label }))}
                placeholder="Select rule type"
              />
            </FormField>

            {formData.rule_type === 'high_priority_ticket' ? (
              <FormField label="Timing">
                <Box variant="p"><StatusIndicator type="info">Emails are sent immediately when a high-priority ticket is created.</StatusIndicator></Box>
              </FormField>
            ) : formData.rule_type === 'ai_briefing' ? (
              <FormField label="Timing">
                <Box variant="p"><StatusIndicator type="info">An AI operations briefing is emailed weekly (Monday morning) with PDF attached.</StatusIndicator></Box>
              </FormField>
            ) : (
              <FormField label="Days Before" description="How many days before the event to send the reminder.">
                <Input
                  type="number"
                  value={String(formData.days_before)}
                  onChange={({ detail }) =>
                    setFormData({ ...formData, days_before: parseInt(detail.value) || 0 })
                  }
                />
              </FormField>
            )}

            <FormField label="Recipient Emails" description="Press Enter or click Add to add each email.">
              <SpaceBetween size="xs">
                <SpaceBetween direction="horizontal" size="xs">
                  <Input
                    value={emailInput}
                    onChange={({ detail }) => setEmailInput(detail.value)}
                    onKeyDown={({ detail }) => {
                      if (detail.key === 'Enter') {
                        addEmail();
                      }
                    }}
                    placeholder="email@example.com"
                  />
                  <Button onClick={addEmail}>Add</Button>
                </SpaceBetween>
                {formData.recipient_emails.length > 0 && (
                  <TokenGroup
                    items={formData.recipient_emails.map((email) => ({ label: email }))}
                    onDismiss={({ detail }) => {
                      setFormData({
                        ...formData,
                        recipient_emails: formData.recipient_emails.filter((_, i) => i !== detail.itemIndex),
                      });
                    }}
                  />
                )}
              </SpaceBetween>
            </FormField>

            <FormField label="Recipient Roles" description="Active users with these roles are emailed in addition to the addresses above.">
              <Multiselect
                selectedOptions={(formData.recipient_roles ?? []).map((r) => ({ value: r, label: r }))}
                onChange={({ detail }) =>
                  setFormData({ ...formData, recipient_roles: detail.selectedOptions.map((o) => o.value as string) })
                }
                options={[
                  { value: 'admin', label: 'Admin' },
                  { value: 'editor', label: 'Editor' },
                  { value: 'viewer', label: 'Viewer' },
                  { value: 'accountant', label: 'Accountant' },
                ]}
                placeholder="No roles selected"
                deselectAriaLabel={(o) => `Remove ${o.label}`}
              />
            </FormField>

            <FormField label="Delivery Mode" description="Immediate sends one email per event; digests batch multiple notices into one email per recipient.">
              <Select
                selectedOption={{
                  value: formData.delivery_mode ?? 'immediate',
                  label: { immediate: 'Immediate', daily_digest: 'Daily digest', weekly_digest: 'Weekly digest' }[formData.delivery_mode ?? 'immediate'] ?? 'Immediate',
                }}
                onChange={({ detail }) => setFormData({ ...formData, delivery_mode: detail.selectedOption.value })}
                options={[
                  { value: 'immediate', label: 'Immediate' },
                  { value: 'daily_digest', label: 'Daily digest' },
                  { value: 'weekly_digest', label: 'Weekly digest' },
                ]}
              />
            </FormField>

            <FormField
              label="Escalation Day Offsets"
              description="Comma-separated days after the first notice to re-send while unacknowledged (e.g. 3, 7). Leave blank for no escalation."
            >
              <Input
                value={(formData.escalation_offsets ?? []).join(', ')}
                onChange={({ detail }) =>
                  setFormData({
                    ...formData,
                    escalation_offsets: detail.value
                      .split(',')
                      .map((s) => parseInt(s.trim(), 10))
                      .filter((n) => Number.isFinite(n) && n > 0),
                  })
                }
                placeholder="3, 7"
              />
            </FormField>

            <FormField
              label="Escalation Recipient Emails"
              description="Comma-separated extra addresses added once a notice escalates (e.g. a manager or owner)."
            >
              <Input
                value={(formData.escalation_recipient_emails ?? []).join(', ')}
                onChange={({ detail }) =>
                  setFormData({
                    ...formData,
                    escalation_recipient_emails: detail.value
                      .split(',')
                      .map((s) => s.trim())
                      .filter((s) => s.length > 0),
                  })
                }
                placeholder="manager@example.com"
              />
            </FormField>

            <FormField label="Require Acknowledgement" description="Include an acknowledge link; escalation stops once a recipient confirms.">
              <Toggle
                checked={formData.require_acknowledgement ?? false}
                onChange={({ detail }) => setFormData({ ...formData, require_acknowledgement: detail.checked })}
              >
                {formData.require_acknowledgement ? 'Required' : 'Not required'}
              </Toggle>
            </FormField>

            <FormField label="Active">
              <Toggle
                checked={formData.is_active ?? true}
                onChange={({ detail }) => setFormData({ ...formData, is_active: detail.checked })}
              >
                {formData.is_active ? 'Enabled' : 'Disabled'}
              </Toggle>
            </FormField>
          </SpaceBetween>
        </Modal>

        {/* Delete Confirmation */}
        <Modal
          visible={!!deleteTarget}
          onDismiss={() => setDeleteTarget(null)}
          header="Delete Rule"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
                <Button variant="primary" loading={deleting} onClick={handleDelete}>
                  Delete
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          Are you sure you want to delete the rule <strong>{deleteTarget?.rule_name}</strong>? This action cannot be undone.
        </Modal>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default EmailRulesPage;
