import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import CreateWizardModal from '@/components/common/CreateWizardModal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { useAuth } from '@/auth/AuthContext';
import { canMutateOperationalData } from '@/auth/permissions';
import { leasingFunnel, leasing, applicationTemplates } from '@/api';
import type {
  RentalApplication,
  ApplicationStatus,
  ScreeningReport,
  FinancialVerification,
  LeaseSignatureRequest,
  LeaseSignaturePartyInput,
  RentalUnit,
  ApplicationTemplate,
} from '@/types';

interface Opt { label: string; value: string; }

const appBadge = (s: ApplicationStatus) => {
  const color =
    s === 'approved' || s === 'converted' || s === 'signed'
      ? 'green'
      : s === 'denied' || s === 'withdrawn'
        ? 'red'
        : s === 'sent' || s === 'viewed'
          ? 'grey'
          : 'blue';
  return <Badge color={color as 'green' | 'red' | 'blue' | 'grey'}>{s.replace('_', ' ')}</Badge>;
};

const sigBadge = (s: string) => {
  const color = s === 'completed' ? 'green' : s === 'voided' ? 'red' : 'blue';
  return <Badge color={color as 'green' | 'red' | 'blue'}>{s}</Badge>;
};

const LeasingFunnelPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const { user } = useAuth();
  const canEdit = canMutateOperationalData(user?.role);
  const [apps, setApps] = useState<RentalApplication[]>([]);
  const [signatures, setSignatures] = useState<LeaseSignatureRequest[]>([]);
  const [units, setUnits] = useState<RentalUnit[]>([]);
  const [templates, setTemplates] = useState<ApplicationTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  // Application modal
  const [appOpen, setAppOpen] = useState(false);
  const [unitId, setUnitId] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [income, setIncome] = useState('');
  const [savingApp, setSavingApp] = useState(false);

  // Send-application (from template) modal
  const [sendOpen, setSendOpen] = useState(false);
  const [sendTemplateId, setSendTemplateId] = useState('');
  const [sendFirst, setSendFirst] = useState('');
  const [sendLast, setSendLast] = useState('');
  const [sendEmail, setSendEmail] = useState('');
  const [sendPhone, setSendPhone] = useState('');
  const [sendUnitId, setSendUnitId] = useState('');
  const [sendingApp, setSendingApp] = useState(false);

  // Screening detail modal
  const [screenOpen, setScreenOpen] = useState(false);
  const [screenReports, setScreenReports] = useState<ScreeningReport[]>([]);

  // Applicant financial verification
  const [financialRequestApp, setFinancialRequestApp] = useState<RentalApplication | null>(null);
  const [financialOpen, setFinancialOpen] = useState(false);
  const [financialRows, setFinancialRows] = useState<FinancialVerification[]>([]);
  const [financialBusy, setFinancialBusy] = useState(false);

  // Signature modal
  const [sigOpen, setSigOpen] = useState(false);
  const [sigTitle, setSigTitle] = useState('');
  const [sigBody, setSigBody] = useState('');
  const [parties, setParties] = useState<LeaseSignaturePartyInput[]>([
    { signer_name: '', signer_email: '', role: 'tenant' },
  ]);
  const [savingSig, setSavingSig] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, s, u, t] = await Promise.all([
        leasingFunnel.listApplications(),
        leasingFunnel.listSignatures(),
        leasing.listUnits(),
        applicationTemplates.list(),
      ]);
      setApps(a.data);
      setSignatures(s.data);
      setUnits(u.data);
      setTemplates(t.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load leasing funnel.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const unitOptions: Opt[] = useMemo(
    () => [
      { label: '— No unit —', value: '' },
      ...units.map((u) => ({
        label: u.unit_number + (u.name ? ` · ${u.name}` : ''),
        value: u.id,
      })),
    ],
    [units],
  );

  const templateOptions: Opt[] = useMemo(
    () => [
      { label: '— Default template —', value: '' },
      ...templates.map((t) => ({
        label: t.name + (t.is_default ? ' (default)' : ''),
        value: t.id,
      })),
    ],
    [templates],
  );

  const openApp = () => {
    setUnitId('');
    setFirstName('');
    setLastName('');
    setEmail('');
    setPhone('');
    setIncome('');
    setAppOpen(true);
  };

  const saveApp = async () => {
    if (!firstName.trim() || !lastName.trim() || !email.trim()) {
      addFlash({ type: 'error', content: 'Applicant name and email are required.' });
      return;
    }
    setSavingApp(true);
    try {
      await leasingFunnel.createApplication({
        unit_id: unitId || null,
        applicant_first_name: firstName.trim(),
        applicant_last_name: lastName.trim(),
        applicant_email: email.trim(),
        applicant_phone: phone.trim() || null,
        monthly_income: income.trim() || null,
      });
      addFlash({ type: 'success', content: 'Application created.' });
      setAppOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to create application.' });
    } finally {
      setSavingApp(false);
    }
  };

  const sendFromTemplate = async () => {
    if (!sendFirst.trim() || !sendLast.trim() || !sendEmail.trim()) {
      addFlash({ type: 'error', content: 'Applicant name and email are required.' });
      return;
    }
    setSendingApp(true);
    try {
      await leasingFunnel.createApplicationFromTemplate({
        template_id: sendTemplateId || null,
        unit_id: sendUnitId || null,
        applicant_first_name: sendFirst.trim(),
        applicant_last_name: sendLast.trim(),
        applicant_email: sendEmail.trim(),
        applicant_phone: sendPhone.trim() || null,
      });
      addFlash({ type: 'success', content: `Application sent to ${sendEmail.trim()}.` });
      setSendOpen(false);
      setSendFirst('');
      setSendLast('');
      setSendEmail('');
      setSendPhone('');
      setSendUnitId('');
      setSendTemplateId('');
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to send application.' });
    } finally {
      setSendingApp(false);
    }
  };

  const resend = async (a: RentalApplication) => {
    try {
      await leasingFunnel.sendApplication(a.id);
      addFlash({ type: 'success', content: 'Application re-sent.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to re-send application.' });
    }
  };

  const runScreen = async (a: RentalApplication) => {
    try {
      await leasingFunnel.screen(a.id);
      addFlash({ type: 'success', content: 'Screening requested.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to run screening.' });
    }
  };

  const viewScreening = async (a: RentalApplication) => {
    try {
      const r = await leasingFunnel.listScreening(a.id);
      setScreenReports(r.data);
      setScreenOpen(true);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load screening reports.' });
    }
  };

  const requestFinancialVerification = async () => {
    if (!financialRequestApp) return;
    setFinancialBusy(true);
    try {
      await leasingFunnel.requestFinancialVerification(financialRequestApp.id);
      addFlash({ type: 'success', content: `Financial verification sent to ${financialRequestApp.applicant_email}.` });
      setFinancialRequestApp(null);
    } catch {
      addFlash({ type: 'error', content: 'Could not send financial verification. Confirm Plaid applicant verification is enabled.' });
    } finally {
      setFinancialBusy(false);
    }
  };

  const viewFinancialVerifications = async (a: RentalApplication) => {
    try {
      const response = await leasingFunnel.listFinancialVerifications(a.id);
      setFinancialRows(response.data);
      setFinancialOpen(true);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load financial verification results.' });
    }
  };

  const resendFinancial = async (row: FinancialVerification) => {
    await leasingFunnel.resendFinancialVerification(row.id);
    setFinancialOpen(false);
    addFlash({ type: 'success', content: 'Financial verification request re-sent.' });
  };

  const cancelFinancial = async (row: FinancialVerification) => {
    await leasingFunnel.cancelFinancialVerification(row.id);
    setFinancialOpen(false);
    addFlash({ type: 'success', content: 'Financial verification request cancelled.' });
  };

  const money = (value: string | null) => value == null
    ? 'Not available'
    : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value));

  const viewSignedApplication = async (a: RentalApplication) => {
    try {
      const res = await leasingFunnel.downloadSignedApplication(a.id);
      const url = window.URL.createObjectURL(
        new Blob([res.data as BlobPart], { type: 'application/pdf' }),
      );
      window.open(url, '_blank', 'noopener');
      // Revoke the object URL after the new tab has had time to load the PDF.
      setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load signed application.' });
    }
  };

  const setStatus = async (a: RentalApplication, status: ApplicationStatus) => {
    try {
      await leasingFunnel.updateApplication(a.id, { status });
      addFlash({ type: 'success', content: `Application marked ${status}.` });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to update application.' });
    }
  };

  const convert = async (a: RentalApplication) => {
    try {
      await leasingFunnel.convert(a.id);
      addFlash({ type: 'success', content: 'Applicant converted to resident.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to convert applicant.' });
    }
  };

  const openSig = () => {
    setSigTitle('');
    setSigBody('');
    setParties([{ signer_name: '', signer_email: '', role: 'tenant' }]);
    setSigOpen(true);
  };

  const updateParty = (i: number, field: keyof LeaseSignaturePartyInput, value: string) => {
    setParties((prev) =>
      prev.map((p, idx) => (idx === i ? { ...p, [field]: value } : p)),
    );
  };

  const saveSig = async () => {
    const valid = parties.filter((p) => p.signer_name.trim() && p.signer_email.trim());
    if (!sigTitle.trim() || !sigBody.trim() || valid.length === 0) {
      addFlash({
        type: 'error',
        content: 'Title, body, and at least one signer are required.',
      });
      return;
    }
    setSavingSig(true);
    try {
      await leasingFunnel.createSignature({
        title: sigTitle.trim(),
        body: sigBody,
        parties: valid.map((p, i) => ({ ...p, sign_order: i + 1 })),
      });
      addFlash({ type: 'success', content: 'Lease signature request created.' });
      setSigOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to create signature request.' });
    } finally {
      setSavingSig(false);
    }
  };

  const voidSig = async (s: LeaseSignatureRequest) => {
    if (!window.confirm('Void this signature request?')) return;
    try {
      await leasingFunnel.voidSignature(s.id);
      addFlash({ type: 'success', content: 'Signature request voided.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to void request.' });
    }
  };

  const applicantFields = (
    <ColumnLayout columns={2}>
      <FormField label="First name">
        <Input value={firstName} onChange={({ detail }) => setFirstName(detail.value)} />
      </FormField>
      <FormField label="Last name">
        <Input value={lastName} onChange={({ detail }) => setLastName(detail.value)} />
      </FormField>
      <FormField label="Email">
        <Input value={email} onChange={({ detail }) => setEmail(detail.value)} />
      </FormField>
      <FormField label="Phone">
        <Input value={phone} onChange={({ detail }) => setPhone(detail.value)} />
      </FormField>
    </ColumnLayout>
  );

  const applicationUnitFields = (
    <SpaceBetween size="m">
      <FormField label="Unit">
        <Select
          selectedOption={unitOptions.find((o) => o.value === unitId) ?? unitOptions[0]}
          onChange={({ detail }) => setUnitId(detail.selectedOption.value ?? '')}
          options={unitOptions}
          filteringType="auto"
        />
      </FormField>
      <FormField label="Monthly income">
        <Input type="number" value={income} onChange={({ detail }) => setIncome(detail.value)} />
      </FormField>
    </SpaceBetween>
  );

  const sendApplicantFields = (
    <ColumnLayout columns={2}>
      <FormField label="First name">
        <Input value={sendFirst} onChange={({ detail }) => setSendFirst(detail.value)} />
      </FormField>
      <FormField label="Last name">
        <Input value={sendLast} onChange={({ detail }) => setSendLast(detail.value)} />
      </FormField>
      <FormField label="Email">
        <Input value={sendEmail} onChange={({ detail }) => setSendEmail(detail.value)} />
      </FormField>
      <FormField label="Phone">
        <Input value={sendPhone} onChange={({ detail }) => setSendPhone(detail.value)} />
      </FormField>
    </ColumnLayout>
  );

  const sendTemplateFields = (
    <SpaceBetween size="m">
      <FormField
        label="Application template"
        description="Leave blank to use the organization's default template."
      >
        <Select
          selectedOption={
            templateOptions.find((o) => o.value === sendTemplateId) ?? templateOptions[0]
          }
          onChange={({ detail }) => setSendTemplateId(detail.selectedOption.value ?? '')}
          options={templateOptions}
          filteringType="auto"
        />
      </FormField>
      <FormField label="Unit">
        <Select
          selectedOption={unitOptions.find((o) => o.value === sendUnitId) ?? unitOptions[0]}
          onChange={({ detail }) => setSendUnitId(detail.selectedOption.value ?? '')}
          options={unitOptions}
          filteringType="auto"
        />
      </FormField>
    </SpaceBetween>
  );

  const sigDocumentFields = (
    <SpaceBetween size="m">
      <FormField label="Title">
        <Input value={sigTitle} onChange={({ detail }) => setSigTitle(detail.value)} />
      </FormField>
      <FormField label="Lease document text">
        <Textarea
          value={sigBody}
          onChange={({ detail }) => setSigBody(detail.value)}
          rows={6}
        />
      </FormField>
    </SpaceBetween>
  );

  const sigPartyFields = (
    <FormField
      label="Signers"
      secondaryControl={
        <Button
          onClick={() =>
            setParties((p) => [...p, { signer_name: '', signer_email: '', role: 'tenant' }])
          }
        >
          Add signer
        </Button>
      }
    >
      <SpaceBetween size="xs">
        {parties.map((p, i) => (
          <ColumnLayout key={i} columns={3}>
            <Input
              placeholder="Name"
              value={p.signer_name}
              onChange={({ detail }) => updateParty(i, 'signer_name', detail.value)}
            />
            <Input
              placeholder="Email"
              value={p.signer_email}
              onChange={({ detail }) => updateParty(i, 'signer_email', detail.value)}
            />
            <Input
              placeholder="Role"
              value={p.role ?? 'tenant'}
              onChange={({ detail }) => updateParty(i, 'role', detail.value)}
            />
          </ColumnLayout>
        ))}
      </SpaceBetween>
    </FormField>
  );

  const appDirty = Boolean(unitId || firstName || lastName || email || phone || income);

  const sendDirty = Boolean(
    sendTemplateId || sendUnitId || sendFirst || sendLast || sendEmail || sendPhone,
  );

  const sigDirty = Boolean(
    sigTitle || sigBody || parties.some((p) => p.signer_name || p.signer_email),
  );

  return (
    <SpaceBetween size="l">
      <Table<RentalApplication>
        loading={loading}
        items={apps}
        variant="container"
        header={
          <Header
            counter={`(${apps.length})`}
            actions={canEdit ? (
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => setSendOpen(true)}>Send application</Button>
                <Button variant="primary" onClick={openApp}>
                  Add application
                </Button>
              </SpaceBetween>
            ) : undefined}
          >
            Rental applications
          </Header>
        }
        columnDefinitions={[
          {
            id: 'applicant',
            header: 'Applicant',
            cell: (a) => `${a.applicant_first_name} ${a.applicant_last_name}`,
          },
          { id: 'email', header: 'Email', cell: (a) => a.applicant_email },
          { id: 'status', header: 'Status', cell: (a) => appBadge(a.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (a) => (
              <SpaceBetween direction="horizontal" size="xs">
                {canEdit && a.application_template_id &&
                  (a.status === 'sent' || a.status === 'viewed' || a.status === 'draft') && (
                    <Button variant="inline-link" onClick={() => resend(a)}>
                      Resend
                    </Button>
                  )}
                {canEdit && (
                  <Button variant="inline-link" onClick={() => runScreen(a)}>
                    Background screening
                  </Button>
                )}
                <Button variant="inline-link" onClick={() => viewScreening(a)}>
                  Screening reports
                </Button>
                {canEdit && ['submitted', 'signed', 'in_review', 'screening'].includes(a.status) && (
                  <Button variant="inline-link" onClick={() => setFinancialRequestApp(a)}>
                    Request financial verification
                  </Button>
                )}
                <Button variant="inline-link" onClick={() => viewFinancialVerifications(a)}>
                  Financial verification
                </Button>
                {a.signed_at && (
                  <Button variant="inline-link" onClick={() => viewSignedApplication(a)}>
                    View signed
                  </Button>
                )}
                {canEdit && a.status !== 'approved' && a.status !== 'converted' && (
                  <Button variant="inline-link" onClick={() => setStatus(a, 'approved')}>
                    Approve
                  </Button>
                )}
                {canEdit && a.status !== 'denied' && a.status !== 'converted' && (
                  <Button variant="inline-link" onClick={() => setStatus(a, 'denied')}>
                    Deny
                  </Button>
                )}
                {canEdit && a.status === 'approved' && (
                  <Button variant="inline-link" onClick={() => convert(a)}>
                    Convert
                  </Button>
                )}
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No applications yet.</Box>}
      />

      <Table<LeaseSignatureRequest>
        loading={loading}
        items={signatures}
        variant="container"
        header={
          <Header
            counter={`(${signatures.length})`}
            actions={canEdit ? (
              <Button variant="primary" onClick={openSig}>
                New signature request
              </Button>
            ) : undefined}
          >
            Lease signature requests
          </Header>
        }
        columnDefinitions={[
          { id: 'title', header: 'Title', cell: (s) => s.title },
          {
            id: 'parties',
            header: 'Signers',
            cell: (s) =>
              s.parties
                .map((p) => `${p.signer_name} (${p.status})`)
                .join(', ') || '—',
          },
          { id: 'status', header: 'Status', cell: (s) => sigBadge(s.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (s) =>
              s.status !== 'completed' && s.status !== 'voided' ? (
                <Button variant="inline-link" onClick={() => voidSig(s)}>
                  Void
                </Button>
              ) : (
                '—'
              ),
          },
        ]}
        empty={<Box textAlign="center">No signature requests yet.</Box>}
      />

      <CreateWizardModal
        visible={canEdit && appOpen}
        entityLabel="rental application"
        onCancel={() => setAppOpen(false)}
        onSubmit={saveApp}
        submitting={savingApp}
        dirty={appDirty}
        onBulkComplete={load}
        bulk={{
          columns: [
            { key: 'applicant_first_name', label: 'First name', required: true },
            { key: 'applicant_last_name', label: 'Last name', required: true },
            { key: 'applicant_email', label: 'Email', required: true },
            { key: 'applicant_phone', label: 'Phone' },
            { key: 'monthly_income', label: 'Monthly income' },
          ],
          onSubmitRow: async (row) => {
            await leasingFunnel.createApplication({
              unit_id: null,
              applicant_first_name: row.applicant_first_name.trim(),
              applicant_last_name: row.applicant_last_name.trim(),
              applicant_email: row.applicant_email.trim(),
              applicant_phone: row.applicant_phone?.trim() || null,
              monthly_income: row.monthly_income?.trim() || null,
            });
          },
        }}
        steps={[
          {
            title: 'Applicant',
            description: 'Who is applying, and how to reach them.',
            content: applicantFields,
            validate: () =>
              !firstName.trim() || !lastName.trim() || !email.trim()
                ? 'Applicant name and email are required.'
                : null,
          },
          {
            title: 'Unit & income',
            description: 'What they are applying for, and what they earn.',
            content: applicationUnitFields,
          },
        ]}
      />

      <CreateWizardModal
        visible={canEdit && sendOpen}
        entityLabel="application invite"
        onCancel={() => setSendOpen(false)}
        onSubmit={sendFromTemplate}
        submitting={sendingApp}
        dirty={sendDirty}
        steps={[
          {
            title: 'Applicant',
            description: 'Who receives the application to fill out.',
            content: sendApplicantFields,
            validate: () =>
              !sendFirst.trim() || !sendLast.trim() || !sendEmail.trim()
                ? 'Applicant name and email are required.'
                : null,
          },
          {
            title: 'Template & unit',
            description: 'Which form to send, and for which unit.',
            content: sendTemplateFields,
          },
        ]}
      />

      <Modal
        visible={screenOpen}
        onDismiss={() => setScreenOpen(false)}
        header="Screening reports"
        footer={
          <Box float="right">
            <Button variant="primary" onClick={() => setScreenOpen(false)}>
              Close
            </Button>
          </Box>
        }
      >
        {screenReports.length === 0 ? (
          <Box>No screening reports for this application.</Box>
        ) : (
          <SpaceBetween size="m">
            {screenReports.map((r) => (
              <ColumnLayout key={r.id} columns={2} variant="text-grid">
                <div>
                  <Box variant="awsui-key-label">Provider</Box>
                  <Box>{r.provider}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Recommendation</Box>
                  <Box>{r.recommendation}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Status</Box>
                  <Box>{r.status}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Credit score</Box>
                  <Box>{r.credit_score ?? '—'}</Box>
                </div>
              </ColumnLayout>
            ))}
          </SpaceBetween>
        )}
      </Modal>

      <Modal
        visible={financialRequestApp !== null}
        onDismiss={() => setFinancialRequestApp(null)}
        header="Request financial verification (Plaid)"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setFinancialRequestApp(null)}>Cancel</Button>
              <Button variant="primary" loading={financialBusy} onClick={requestFinancialVerification}>Send request</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box>
            Send to <strong>{financialRequestApp?.applicant_email}</strong>. The applicant will review a disclosure and must explicitly consent before Plaid Link opens.
          </Box>
          <Box variant="h3">Requested checks</Box>
          <ul>
            <li>Account ownership and applicant identity match</li>
            <li>Connected account availability</li>
            <li>Aggregate current and available balances</li>
            <li>Recurring income estimate from up to 90 days of transactions</li>
          </ul>
          <Box color="text-body-secondary">
            Financial verification is decision support only. It is separate from background screening and must not automatically approve or deny an application.
          </Box>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={financialOpen}
        onDismiss={() => setFinancialOpen(false)}
        header="Financial verification (Plaid)"
        size="large"
        footer={<Box float="right"><Button variant="primary" onClick={() => setFinancialOpen(false)}>Close</Button></Box>}
      >
        {financialRows.length === 0 ? <Box>No financial verification requests for this application.</Box> : (
          <SpaceBetween size="l">
            {financialRows.map((row) => (
              <SpaceBetween key={row.id} size="m">
                <ColumnLayout columns={3} variant="text-grid">
                  <div><Box variant="awsui-key-label">Status</Box><Box>{row.status.replace('_', ' ')}</Box></div>
                  <div><Box variant="awsui-key-label">Consent</Box><Box>{row.consented_at ? new Date(row.consented_at).toLocaleString() : 'Not provided'}</Box></div>
                  <div><Box variant="awsui-key-label">Institution</Box><Box>{row.institution_name ?? 'Not available'}</Box></div>
                  <div><Box variant="awsui-key-label">Identity match</Box><Box>{row.identity_match == null ? 'Not available' : row.identity_match ? 'Matched' : 'Review needed'}</Box></div>
                  <div><Box variant="awsui-key-label">Ownership match</Box><Box>{row.ownership_match == null ? 'Not available' : row.ownership_match ? 'Matched' : 'Review needed'}</Box></div>
                  <div><Box variant="awsui-key-label">Connected accounts</Box><Box>{row.account_count ?? 'Not available'}</Box></div>
                  <div><Box variant="awsui-key-label">Aggregate available balance</Box><Box>{money(row.available_balance_total)}</Box></div>
                  <div><Box variant="awsui-key-label">Aggregate current balance</Box><Box>{money(row.current_balance_total)}</Box></div>
                  <div><Box variant="awsui-key-label">Estimated recurring monthly income</Box><Box>{money(row.recurring_income_monthly)}</Box></div>
                  <div><Box variant="awsui-key-label">Income months observed</Box><Box>{row.income_months_observed ?? 'Not available'}</Box></div>
                  <div><Box variant="awsui-key-label">Decision support recommendation</Box><Box>{row.recommendation}</Box></div>
                  <div><Box variant="awsui-key-label">Reason codes</Box><Box>{row.reason_codes.join(', ') || 'None'}</Box></div>
                </ColumnLayout>
                {row.last_error && <Alert type="error">{row.last_error}</Alert>}
                <Box color="text-body-secondary">{row.decision_support_disclaimer}</Box>
                {canEdit && ['invited', 'viewed', 'action_required', 'error', 'expired'].includes(row.status) && (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={() => resendFinancial(row)}>Resend</Button>
                    <Button onClick={() => cancelFinancial(row)}>Cancel request</Button>
                  </SpaceBetween>
                )}
              </SpaceBetween>
            ))}
          </SpaceBetween>
        )}
      </Modal>

      <CreateWizardModal
        visible={canEdit && sigOpen}
        entityLabel="lease signature request"
        onCancel={() => setSigOpen(false)}
        onSubmit={saveSig}
        submitting={savingSig}
        dirty={sigDirty}
        steps={[
          {
            title: 'Document',
            description: 'Title the request and paste the lease text to sign.',
            content: sigDocumentFields,
            validate: () =>
              !sigTitle.trim() || !sigBody.trim()
                ? 'Title, body, and at least one signer are required.'
                : null,
          },
          {
            title: 'Signers',
            description: 'Who signs, in the order they are listed.',
            content: sigPartyFields,
            validate: () =>
              parties.filter((p) => p.signer_name.trim() && p.signer_email.trim()).length === 0
                ? 'Title, body, and at least one signer are required.'
                : null,
          },
        ]}
      />
    </SpaceBetween>
  );
};

export default LeasingFunnelPage;
