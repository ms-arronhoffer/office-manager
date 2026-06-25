import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import DatePicker from '@cloudscape-design/components/date-picker';
import Checkbox from '@cloudscape-design/components/checkbox';
import { leases as leasesApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type {
  AbstractClause,
  AbstractClauseStatus,
  AbstractFieldSchema,
  AbstractSummary,
} from '@/types';

const STATUS_LABELS: Record<AbstractClauseStatus, string> = {
  contains_content: 'Contains Content',
  needs_content: 'Needs Content',
  incomplete: 'Incomplete',
};

const STATUS_INDICATOR: Record<AbstractClauseStatus, 'success' | 'error' | 'warning'> = {
  contains_content: 'success',
  needs_content: 'error',
  incomplete: 'warning',
};

const GROUP_ORDER = ['financial', 'clauses', 'rights'];

function emptySummary(): AbstractSummary {
  return { total: 0, contains_content: 0, needs_content: 0, incomplete: 0 };
}

function summarize(clauses: AbstractClause[]): AbstractSummary {
  const counts = emptySummary();
  counts.total = clauses.length;
  for (const c of clauses) counts[c.status] += 1;
  return counts;
}

interface ClauseEditModalProps {
  leaseId: string;
  clause: AbstractClause;
  onClose: () => void;
  onSaved: (updated: AbstractClause) => void;
}

const ClauseEditModal: React.FC<ClauseEditModalProps> = ({ leaseId, clause, onClose, onSaved }) => {
  const { addFlash } = useFlashbar();
  const [content, setContent] = useState<Record<string, unknown>>(() => ({ ...(clause.content ?? {}) }));
  const [notes, setNotes] = useState<string>(clause.notes ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setField = (key: string, value: unknown) =>
    setContent((prev) => ({ ...prev, [key]: value }));

  const renderField = (field: AbstractFieldSchema) => {
    const raw = content[field.key];
    switch (field.type) {
      case 'textarea':
        return (
          <Textarea
            value={raw == null ? '' : String(raw)}
            onChange={({ detail }) => setField(field.key, detail.value)}
          />
        );
      case 'date':
        return (
          <DatePicker
            value={raw == null ? '' : String(raw)}
            onChange={({ detail }) => setField(field.key, detail.value)}
            placeholder="YYYY/MM/DD"
          />
        );
      case 'boolean':
        return (
          <Checkbox
            checked={Boolean(raw)}
            onChange={({ detail }) => setField(field.key, detail.checked)}
          >
            Yes
          </Checkbox>
        );
      case 'select': {
        const options = (field.options ?? []).map((o) => ({ label: o, value: o }));
        const selected = options.find((o) => o.value === raw) ?? null;
        return (
          <Select
            selectedOption={selected}
            options={options}
            onChange={({ detail }) => setField(field.key, detail.selectedOption?.value ?? null)}
            placeholder="Select"
          />
        );
      }
      case 'currency':
      case 'number':
      case 'percent':
        return (
          <Input
            type="number"
            value={raw == null ? '' : String(raw)}
            onChange={({ detail }) =>
              setField(field.key, detail.value === '' ? null : Number(detail.value))
            }
          />
        );
      default:
        return (
          <Input
            value={raw == null ? '' : String(raw)}
            onChange={({ detail }) => setField(field.key, detail.value)}
          />
        );
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      // Drop empty values so completeness derivation stays accurate.
      const cleaned: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(content)) {
        if (v !== null && v !== undefined && v !== '') cleaned[k] = v;
      }
      const updated = await leasesApi.updateAbstractClause(leaseId, clause.category_key, {
        content: cleaned,
        notes: notes.trim() === '' ? null : notes,
      });
      addFlash({ type: 'success', content: `${clause.name} saved`, dismissible: true });
      onSaved(updated.data);
    } catch {
      setError('Failed to save clause. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      visible
      onDismiss={onClose}
      header={clause.name}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleSave} loading={saving}>
              Save
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        {error && <Alert type="error">{error}</Alert>}
        {clause.fields
          .filter((f) => f.key !== 'notes')
          .map((field) => (
            <FormField key={field.key} label={field.label}>
              {renderField(field)}
            </FormField>
          ))}
        <FormField label="Notes">
          <Textarea value={notes} onChange={({ detail }) => setNotes(detail.value)} />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
};

interface LeaseAbstractSectionProps {
  leaseId: string;
  canEdit: boolean;
}

const LeaseAbstractSection: React.FC<LeaseAbstractSectionProps> = ({ leaseId, canEdit }) => {
  const [clauses, setClauses] = useState<AbstractClause[]>([]);
  const [summary, setSummary] = useState<AbstractSummary>(emptySummary);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<AbstractClause | null>(null);

  const fetchAbstract = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await leasesApi.getAbstract(leaseId);
      setClauses(data.clauses);
      setSummary(data.summary);
    } catch {
      setError('Failed to load lease abstract.');
    } finally {
      setLoading(false);
    }
  }, [leaseId]);

  useEffect(() => {
    void fetchAbstract();
  }, [fetchAbstract]);

  const grouped = useMemo(() => {
    const byGroup: Record<string, AbstractClause[]> = {};
    for (const c of clauses) {
      (byGroup[c.group] ??= []).push(c);
    }
    for (const g of Object.keys(byGroup)) {
      byGroup[g].sort((a, b) => a.order - b.order);
    }
    return byGroup;
  }, [clauses]);

  const handleSaved = (updated: AbstractClause) => {
    setClauses((prev) => {
      const next = prev.map((c) => (c.category_key === updated.category_key ? updated : c));
      setSummary(summarize(next));
      return next;
    });
    setEditing(null);
  };

  const renderClauseRow = (clause: AbstractClause) => (
    <Box key={clause.category_key} padding={{ vertical: 'xxs' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
        }}
      >
        <StatusIndicator type={STATUS_INDICATOR[clause.status]}>{clause.name}</StatusIndicator>
        {canEdit && (
          <Button
            variant="icon"
            iconName="settings"
            ariaLabel={`Edit ${clause.name}`}
            onClick={() => setEditing(clause)}
          />
        )}
      </div>
    </Box>
  );

  const groupKeys = useMemo(() => {
    const present = Object.keys(grouped);
    const ordered = GROUP_ORDER.filter((g) => present.includes(g));
    const extra = present.filter((g) => !GROUP_ORDER.includes(g));
    return [...ordered, ...extra];
  }, [grouped]);

  const columns = (Math.min(groupKeys.length || 1, 3) as 1 | 2 | 3);

  return (
    <Container
      header={
        <Header
          variant="h2"
          counter={`(${summary.contains_content}/${summary.total})`}
          description="Structured clause-by-clause lease abstract"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <StatusIndicator type="success">
                {STATUS_LABELS.contains_content}
              </StatusIndicator>
              <StatusIndicator type="error">{STATUS_LABELS.needs_content}</StatusIndicator>
              <StatusIndicator type="warning">{STATUS_LABELS.incomplete}</StatusIndicator>
            </SpaceBetween>
          }
        >
          Lease Abstract
        </Header>
      }
    >
      {loading ? (
        <Box textAlign="center" padding="l">
          <Spinner size="normal" />
        </Box>
      ) : error ? (
        <Alert type="error" action={<Button onClick={() => void fetchAbstract()}>Retry</Button>}>
          {error}
        </Alert>
      ) : (
        <ColumnLayout columns={columns} borders="vertical">
          {groupKeys.map((g) => (
            <SpaceBetween key={g} size="xxs">
              {grouped[g].map(renderClauseRow)}
            </SpaceBetween>
          ))}
        </ColumnLayout>
      )}

      {editing && (
        <ClauseEditModal
          leaseId={leaseId}
          clause={editing}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
        />
      )}
    </Container>
  );
};

export default LeaseAbstractSection;
