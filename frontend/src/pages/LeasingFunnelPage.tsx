import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import EntityFormModal from '@/components/common/EntityFormModal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { leasingFunnel, leasing } from '@/api';
import type {
  RentalApplication,
  ApplicationStatus,
  ScreeningReport,
  LeaseSignatureRequest,
  LeaseSignaturePartyInput,
  RentalUnit,
} from '@/types';

interface Opt { label: string; value: string; }

const appBadge = (s: ApplicationStatus) => {
  const color =
    s === 'approved' || s === 'converted'
      ? 'green'
      : s === 'denied' || s === 'withdrawn'
        ? 'red'
        : 'blue';
  return <Badge color={color as 'green' | 'red' | 'blue'}>{s}</Badge>;
};

const sigBadge = (s: string) => {
  const color = s === 'completed' ? 'green' : s === 'voided' ? 'red' : 'blue';
  return <Badge color={color as 'green' | 'red' | 'blue'}>{s}</Badge>;
};

const LeasingFunnelPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [apps, setApps] = useState<RentalApplication[]>([]);
  const [signatures, setSignatures] = useState<LeaseSignatureRequest[]>([]);
  const [units, setUnits] = useState<RentalUnit[]>([]);
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

  // Screening detail modal
  const [screenOpen, setScreenOpen] = useState(false);
  const [screenReports, setScreenReports] = useState<ScreeningReport[]>([]);

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
      const [a, s, u] = await Promise.all([
        leasingFunnel.listApplications(),
        leasingFunnel.listSignatures(),
        leasing.listUnits(),
      ]);
      setApps(a.data);
      setSignatures(s.data);
      setUnits(u.data);
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

  return (
    <SpaceBetween size="l">
      <Table<RentalApplication>
        loading={loading}
        items={apps}
        variant="container"
        header={
          <Header
            counter={`(${apps.length})`}
            actions={
              <Button variant="primary" onClick={openApp}>
                Add application
              </Button>
            }
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
                <Button variant="inline-link" onClick={() => runScreen(a)}>
                  Screen
                </Button>
                <Button variant="inline-link" onClick={() => viewScreening(a)}>
                  Reports
                </Button>
                {a.status !== 'approved' && a.status !== 'converted' && (
                  <Button variant="inline-link" onClick={() => setStatus(a, 'approved')}>
                    Approve
                  </Button>
                )}
                {a.status !== 'denied' && a.status !== 'converted' && (
                  <Button variant="inline-link" onClick={() => setStatus(a, 'denied')}>
                    Deny
                  </Button>
                )}
                {a.status === 'approved' && (
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
            actions={
              <Button variant="primary" onClick={openSig}>
                New signature request
              </Button>
            }
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

      <EntityFormModal
        visible={appOpen}
        onCancel={() => setAppOpen(false)}
        title="Add application"
        submitLabel="Save"
        submitting={savingApp}
        onSubmit={saveApp}
      >
        <SpaceBetween size="m">
          <FormField label="Unit">
            <Select
              selectedOption={unitOptions.find((o) => o.value === unitId) ?? unitOptions[0]}
              onChange={({ detail }) => setUnitId(detail.selectedOption.value ?? '')}
              options={unitOptions}
              filteringType="auto"
            />
          </FormField>
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
            <FormField label="Monthly income">
              <Input type="number" value={income} onChange={({ detail }) => setIncome(detail.value)} />
            </FormField>
          </ColumnLayout>
        </SpaceBetween>
      </EntityFormModal>

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

      <EntityFormModal
        visible={sigOpen}
        onCancel={() => setSigOpen(false)}
        title="New lease signature request"
        submitLabel="Send"
        submitting={savingSig}
        onSubmit={saveSig}
      >
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
        </SpaceBetween>
      </EntityFormModal>
    </SpaceBetween>
  );
};

export default LeasingFunnelPage;
