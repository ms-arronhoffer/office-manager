import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import Flashbar from '@cloudscape-design/components/flashbar';
import Tabs from '@cloudscape-design/components/tabs';
import { ownerPortal } from '@/api';
import type {
  OwnerPortalBalance,
  OwnerPortalDistribution,
  OwnerPortalLedgerEntry,
  OwnerPortalProfile,
  OwnerPortalProperty,
  OwnerPortalStatement,
} from '@/types';

const formatMoney = (amount: string | number | null | undefined, currency: string) => {
  const value = Number(amount ?? 0);
  if (Number.isNaN(value)) return `${amount ?? '—'}`;
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
};

const formatDate = (d: string | null | undefined) => (d ? d.slice(0, 10) : '—');

const formatPercent = (p: string | null | undefined) => {
  const value = Number(p ?? 0);
  if (Number.isNaN(value)) return `${p ?? '—'}`;
  return `${value}%`;
};

const distributionStatusColor = (s: string): 'green' | 'blue' | 'grey' | 'red' => {
  if (s === 'paid') return 'green';
  if (s === 'pending' || s === 'scheduled') return 'blue';
  if (s === 'cancelled' || s === 'failed') return 'red';
  return 'grey';
};

const OwnerPortalPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  // The single-use invite lands on /owner-portal/signup?token=...; the
  // persistent portal link is /owner-portal?token=...
  const isSignupRoute = location.pathname.endsWith('/signup');
  const urlToken = searchParams.get('token') ?? '';
  const signupToken = isSignupRoute ? urlToken : '';
  const tokenParam = isSignupRoute ? '' : urlToken;

  const [token, setToken] = useState(tokenParam);
  const [profile, setProfile] = useState<OwnerPortalProfile | null>(null);
  const [properties, setProperties] = useState<OwnerPortalProperty[]>([]);
  const [ledger, setLedger] = useState<OwnerPortalLedgerEntry[]>([]);
  const [balance, setBalance] = useState<OwnerPortalBalance | null>(null);
  const [distributions, setDistributions] = useState<OwnerPortalDistribution[]>([]);
  const [statement, setStatement] = useState<OwnerPortalStatement | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);
  const [flash, setFlash] = useState<{ type: 'success' | 'error'; content: string } | null>(null);

  // Statement filters
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loadingStatement, setLoadingStatement] = useState(false);

  const redeemSignup = useCallback(async () => {
    try {
      const res = await ownerPortal.signup(signupToken);
      const newToken = res.data.portal_token;
      setToken(newToken);
      navigate(`/owner-portal?token=${newToken}`, { replace: true });
      return newToken;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 400) {
        setFlash({ type: 'error', content: 'This signup link has expired. Please request a new one.' });
      }
      setAuthError(true);
      return '';
    }
  }, [signupToken, navigate]);

  const loadData = useCallback(async (activeToken: string) => {
    try {
      const [profileRes, propsRes, ledgerRes, balanceRes, distRes, stmtRes] = await Promise.all([
        ownerPortal.getProfile(activeToken),
        ownerPortal.listProperties(activeToken),
        ownerPortal.listLedger(activeToken),
        ownerPortal.getBalance(activeToken),
        ownerPortal.listDistributions(activeToken),
        ownerPortal.getStatement(activeToken),
      ]);
      setProfile(profileRes.data);
      setProperties(propsRes.data);
      setLedger(ledgerRes.data);
      setBalance(balanceRes.data);
      setDistributions(distRes.data);
      setStatement(stmtRes.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        setAuthError(true);
      } else {
        setFlash({ type: 'error', content: 'Failed to load portal data.' });
      }
    }
  }, []);

  const init = useCallback(async () => {
    setLoading(true);
    let activeToken = tokenParam;
    if (signupToken) {
      activeToken = await redeemSignup();
    }
    if (!activeToken) {
      setAuthError(true);
      setLoading(false);
      return;
    }
    await loadData(activeToken);
    setLoading(false);
  }, [tokenParam, signupToken, redeemSignup, loadData]);

  useEffect(() => {
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRunStatement = async () => {
    setLoadingStatement(true);
    try {
      const res = await ownerPortal.getStatement(token, startDate || undefined, endDate || undefined);
      setStatement(res.data);
    } catch {
      setFlash({ type: 'error', content: 'Failed to load statement.' });
    } finally {
      setLoadingStatement(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (authError || !token) {
    return (
      <Box padding="xxl">
        <Alert type="error" header="Access denied">
          This portal link is invalid or has expired. Please contact your property manager for a new
          link.
        </Alert>
      </Box>
    );
  }

  const currency = balance?.currency ?? profile?.currency ?? 'USD';

  return (
    <ContentLayout
      header={
        <Header variant="h1" description={`Owner portal for ${profile?.name ?? '…'}`}>
          Owner Portal
        </Header>
      }
    >
      <SpaceBetween size="l">
        {flash && (
          <Flashbar
            items={[
              {
                type: flash.type,
                content: flash.content,
                dismissible: true,
                onDismiss: () => setFlash(null),
                id: 'flash',
              },
            ]}
          />
        )}

        <Tabs
          tabs={[
            {
              id: 'overview',
              label: 'Overview',
              content: (
                <SpaceBetween size="l">
                  <Container header={<Header variant="h2">Trust balance</Header>}>
                    <ColumnLayout columns={3} variant="text-grid">
                      <div>
                        <Box variant="awsui-key-label">Current balance</Box>
                        <Box variant="awsui-value-large">
                          {formatMoney(balance?.balance, currency)}
                        </Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Properties</Box>
                        <Box variant="awsui-value-large">{properties.length}</Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Distributions</Box>
                        <Box variant="awsui-value-large">{distributions.length}</Box>
                      </div>
                    </ColumnLayout>
                  </Container>
                  <Container header={<Header variant="h2">Profile</Header>}>
                    <ColumnLayout columns={2} variant="text-grid">
                      <div>
                        <Box variant="awsui-key-label">Name</Box>
                        <div>{profile?.name ?? '—'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Type</Box>
                        <div>{profile?.owner_type ?? '—'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Email</Box>
                        <div>{profile?.email ?? '—'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Phone</Box>
                        <div>{profile?.phone ?? '—'}</div>
                      </div>
                    </ColumnLayout>
                  </Container>
                </SpaceBetween>
              ),
            },
            {
              id: 'properties',
              label: `Properties (${properties.length})`,
              content: (
                <Table
                  items={properties}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No properties assigned.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'office',
                      header: 'Property',
                      cell: (p: OwnerPortalProperty) => p.office_id,
                    },
                    {
                      id: 'percent',
                      header: 'Ownership',
                      cell: (p: OwnerPortalProperty) => formatPercent(p.ownership_percent),
                      width: 140,
                    },
                    {
                      id: 'start',
                      header: 'Start',
                      cell: (p: OwnerPortalProperty) => formatDate(p.start_date),
                    },
                    {
                      id: 'end',
                      header: 'End',
                      cell: (p: OwnerPortalProperty) => formatDate(p.end_date),
                    },
                  ]}
                />
              ),
            },
            {
              id: 'ledger',
              label: `Ledger (${ledger.length})`,
              content: (
                <Table
                  items={ledger}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No ledger activity.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'date',
                      header: 'Date',
                      cell: (e: OwnerPortalLedgerEntry) => formatDate(e.entry_date),
                      width: 140,
                    },
                    {
                      id: 'type',
                      header: 'Type',
                      cell: (e: OwnerPortalLedgerEntry) => e.entry_type,
                    },
                    {
                      id: 'description',
                      header: 'Description',
                      cell: (e: OwnerPortalLedgerEntry) => e.description ?? '—',
                    },
                    {
                      id: 'amount',
                      header: 'Amount',
                      cell: (e: OwnerPortalLedgerEntry) => formatMoney(e.amount, e.currency),
                      width: 140,
                    },
                  ]}
                />
              ),
            },
            {
              id: 'statement',
              label: 'Statement',
              content: (
                <SpaceBetween size="l">
                  <Container header={<Header variant="h2">Statement period</Header>}>
                    <SpaceBetween direction="horizontal" size="s">
                      <FormField label="Start date">
                        <Input
                          type="date"
                          value={startDate}
                          onChange={({ detail }) => setStartDate(detail.value)}
                        />
                      </FormField>
                      <FormField label="End date">
                        <Input
                          type="date"
                          value={endDate}
                          onChange={({ detail }) => setEndDate(detail.value)}
                        />
                      </FormField>
                      <FormField label=" ">
                        <Button loading={loadingStatement} onClick={handleRunStatement}>
                          Run
                        </Button>
                      </FormField>
                    </SpaceBetween>
                  </Container>
                  {statement && (
                    <Container header={<Header variant="h2">Statement</Header>}>
                      <SpaceBetween size="m">
                        <ColumnLayout columns={2} variant="text-grid">
                          <div>
                            <Box variant="awsui-key-label">Opening balance</Box>
                            <div>{formatMoney(statement.opening_balance, statement.currency)}</div>
                          </div>
                          <div>
                            <Box variant="awsui-key-label">Closing balance</Box>
                            <div>{formatMoney(statement.closing_balance, statement.currency)}</div>
                          </div>
                        </ColumnLayout>
                        <Table
                          items={statement.lines}
                          empty={
                            <Box textAlign="center" color="inherit">
                              No activity in this period.
                            </Box>
                          }
                          columnDefinitions={[
                            {
                              id: 'date',
                              header: 'Date',
                              cell: (e: OwnerPortalLedgerEntry) => formatDate(e.entry_date),
                              width: 140,
                            },
                            {
                              id: 'type',
                              header: 'Type',
                              cell: (e: OwnerPortalLedgerEntry) => e.entry_type,
                            },
                            {
                              id: 'description',
                              header: 'Description',
                              cell: (e: OwnerPortalLedgerEntry) => e.description ?? '—',
                            },
                            {
                              id: 'amount',
                              header: 'Amount',
                              cell: (e: OwnerPortalLedgerEntry) =>
                                formatMoney(e.amount, e.currency),
                              width: 140,
                            },
                          ]}
                        />
                      </SpaceBetween>
                    </Container>
                  )}
                </SpaceBetween>
              ),
            },
            {
              id: 'distributions',
              label: `Distributions (${distributions.length})`,
              content: (
                <Table
                  items={distributions}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No distributions.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'date',
                      header: 'Date',
                      cell: (d: OwnerPortalDistribution) => formatDate(d.distribution_date),
                      width: 140,
                    },
                    {
                      id: 'amount',
                      header: 'Amount',
                      cell: (d: OwnerPortalDistribution) => formatMoney(d.amount, d.currency),
                      width: 140,
                    },
                    {
                      id: 'method',
                      header: 'Method',
                      cell: (d: OwnerPortalDistribution) => d.method,
                    },
                    {
                      id: 'reference',
                      header: 'Reference',
                      cell: (d: OwnerPortalDistribution) => d.reference ?? '—',
                    },
                    {
                      id: 'status',
                      header: 'Status',
                      cell: (d: OwnerPortalDistribution) => (
                        <Badge color={distributionStatusColor(d.status)}>{d.status}</Badge>
                      ),
                      width: 120,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default OwnerPortalPage;
