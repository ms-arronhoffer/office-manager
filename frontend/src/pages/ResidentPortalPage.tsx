import React, { useCallback, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Spinner from '@cloudscape-design/components/spinner';
import Flashbar from '@cloudscape-design/components/flashbar';
import Tabs from '@cloudscape-design/components/tabs';
import Toggle from '@cloudscape-design/components/toggle';
import Alert from '@cloudscape-design/components/alert';
import Checkbox from '@cloudscape-design/components/checkbox';
import { CardElement, Elements, useElements, useStripe } from '@stripe/react-stripe-js';
import { loadStripe } from '@stripe/stripe-js';
import PortalAccessDenied from '@/components/portal/PortalAccessDenied';
import usePortalSession from '@/hooks/usePortalSession';
import { residentPortal } from '@/api';
import { openPlaidLink } from '@/lib/plaidLink';
import type {
  Attachment,
  ResidentPortalAnnouncement,
  ResidentPortalBalance,
  ResidentPortalLease,
  ResidentPortalPaymentConfig,
  ResidentPortalPaymentMethod,
  ResidentPortalProfile,
  ResidentPortalTicket,
} from '@/types';

const PRIORITY_OPTIONS = [
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
];

const priorityColor = (p: string): 'red' | 'blue' | 'grey' =>
  p === 'high' ? 'red' : p === 'medium' ? 'blue' : 'grey';

const ticketStatusColor = (s: string): 'green' | 'blue' | 'grey' => {
  if (s === 'closed') return 'green';
  if (s === 'in_progress' || s === 'pending_review') return 'blue';
  return 'grey';
};

const formatMoney = (amount: string | null | undefined, currency: string) => {
  const value = Number(amount ?? 0);
  if (Number.isNaN(value)) return `${amount ?? '—'}`;
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
};

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const formatDate = (d: string | null | undefined) => (d ? d.slice(0, 10) : '—');

const methodLabel = (m: ResidentPortalPaymentMethod) => {
  if (m.method_type === 'ach') {
    const bank = m.bank_name || 'Bank account';
    const type = m.account_type ? ` ${m.account_type}` : '';
    const tail = m.last4 ? ` ending ${m.last4}` : '';
    return `${bank}${type}${tail}`;
  }
  const brand = m.brand ? m.brand.toUpperCase() : 'Card';
  const tail = m.last4 ? ` ····${m.last4}` : '';
  const exp = m.exp_month && m.exp_year ? ` (exp ${m.exp_month}/${m.exp_year})` : '';
  return `${brand}${tail}${exp}`;
};

const errorDetail = (err: unknown, fallback: string) =>
  (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

interface AddPaymentMethodModalProps {
  visible: boolean;
  token: string;
  isDefault: boolean;
  onDismiss: () => void;
  onSaved: () => Promise<void>;
  setFlash: (flash: { type: 'success' | 'error'; content: string }) => void;
}

const AddPaymentMethodModal: React.FC<AddPaymentMethodModalProps> = ({
  visible,
  token,
  isDefault,
  onDismiss,
  onSaved,
  setFlash,
}) => {
  const stripe = useStripe();
  const elements = useElements();
  const [saving, setSaving] = useState(false);
  const [cardError, setCardError] = useState<string | null>(null);

  const handleSave = async () => {
    const cardElement = elements?.getElement(CardElement);
    if (!stripe || !cardElement) {
      setCardError('Secure card entry is still loading. Please try again.');
      return;
    }

    setSaving(true);
    setCardError(null);
    try {
      const result = await stripe.createPaymentMethod({ type: 'card', card: cardElement });
      if (result.error) {
        setCardError(result.error.message ?? 'Stripe could not validate this card.');
        return;
      }

      const method = result.paymentMethod;
      if (!method) {
        setCardError('Stripe did not return a payment method. Please try again.');
        return;
      }
      await residentPortal.createPaymentMethod(token, {
        processor_token: method.id,
        brand: method.card?.brand ?? null,
        last4: method.card?.last4 ?? null,
        exp_month: method.card?.exp_month ?? null,
        exp_year: method.card?.exp_year ?? null,
        is_default: isDefault,
      });
      onDismiss();
      setFlash({ type: 'success', content: 'Payment method saved.' });
      await onSaved();
    } catch (err: unknown) {
      setCardError(errorDetail(err, 'Failed to save payment method.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header="Add a payment method"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button variant="primary" loading={saving} disabled={!stripe} onClick={handleSave}>
              Save
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Alert type="info">
          Card details are sent directly to Stripe and never pass through Office Manager.
        </Alert>
        {cardError && <Alert type="error">{cardError}</Alert>}
        <FormField label="Card details">
          <div
            style={{
              border: '1px solid #8d99a8',
              borderRadius: '2px',
              padding: '10px 12px',
              background: '#ffffff',
            }}
          >
            <CardElement
              onChange={(event) => setCardError(event.error?.message ?? null)}
              options={{
                hidePostalCode: false,
                style: {
                  base: {
                    color: '#16191f',
                    fontFamily: 'Amazon Ember, Helvetica Neue, Roboto, Arial, sans-serif',
                    fontSize: '16px',
                    '::placeholder': { color: '#687078' },
                  },
                  invalid: { color: '#d13212' },
                },
              }}
            />
          </div>
        </FormField>
      </SpaceBetween>
    </Modal>
  );
};

const ResidentPortalPage: React.FC = () => {
  const [profile, setProfile] = useState<ResidentPortalProfile | null>(null);
  const [leases, setLeases] = useState<ResidentPortalLease[]>([]);
  const [balance, setBalance] = useState<ResidentPortalBalance | null>(null);
  const [tickets, setTickets] = useState<ResidentPortalTicket[]>([]);
  const [documents, setDocuments] = useState<Attachment[]>([]);
  const [announcements, setAnnouncements] = useState<ResidentPortalAnnouncement[]>([]);
  const [paymentMethods, setPaymentMethods] = useState<ResidentPortalPaymentMethod[]>([]);
  const [paymentConfig, setPaymentConfig] = useState<ResidentPortalPaymentConfig | null>(null);
  const [paymentConfigError, setPaymentConfigError] = useState(false);
  const [stripePromise, setStripePromise] = useState<ReturnType<typeof loadStripe> | null>(null);

  // Maintenance request modal
  const [requestModal, setRequestModal] = useState(false);
  const [requestForm, setRequestForm] = useState<{ subject: string; description: string; priority: string }>({
    subject: '',
    description: '',
    priority: 'medium',
  });
  const [submitting, setSubmitting] = useState(false);

  // Payment flow
  const [payModal, setPayModal] = useState(false);
  const [payAmount, setPayAmount] = useState('');
  const [payKey, setPayKey] = useState('');
  const [payMethodId, setPayMethodId] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [methodModal, setMethodModal] = useState(false);
  const [bankModal, setBankModal] = useState(false);
  const [bankConsent, setBankConsent] = useState(false);
  const [bankBusy, setBankBusy] = useState(false);
  const [bankError, setBankError] = useState<string | null>(null);
  const [recurringConsent, setRecurringConsent] = useState(false);
  const [autopayBusy, setAutopayBusy] = useState(false);
  const [autopaySelection, setAutopaySelection] = useState<string | null>(null);

  const loadData = useCallback(async (activeToken: string) => {
    const configRequest = residentPortal
      .getPaymentConfig(activeToken)
      .then((response) => {
        setPaymentConfig(response.data);
        setPaymentConfigError(false);
        if (
          response.data.configured &&
          response.data.provider.toLowerCase() === 'stripe' &&
          response.data.publishable_key
        ) {
          setStripePromise(loadStripe(response.data.publishable_key));
        }
      })
      .catch(() => setPaymentConfigError(true));
    const [profileRes, leasesRes, balanceRes, ticketsRes, docsRes, annRes, methodsRes] =
      await Promise.all([
        residentPortal.getProfile(activeToken),
        residentPortal.listLeases(activeToken),
        residentPortal.getBalance(activeToken),
        residentPortal.listMaintenanceRequests(activeToken),
        residentPortal.listDocuments(activeToken),
        residentPortal.listAnnouncements(activeToken),
        residentPortal.listPaymentMethods(activeToken),
      ]);
    setProfile(profileRes.data);
    setLeases(leasesRes.data);
    setBalance(balanceRes.data);
    setTickets(ticketsRes.data);
    setDocuments(docsRes.data);
    setAnnouncements(annRes.data);
    setPaymentMethods(methodsRes.data);
    await configRequest;
  }, []);

  const { token, loading, authError, flash, setFlash } = usePortalSession({
    portalPath: '/resident-portal',
    signup: residentPortal.signup,
    exchange: residentPortal.exchange,
    load: loadData,
  });

  const openRequest = () => {
    setRequestForm({ subject: '', description: '', priority: 'medium' });
    setRequestModal(true);
  };

  const handleSubmitRequest = async () => {
    if (!requestForm.subject.trim() || !requestForm.description.trim()) {
      setFlash({ type: 'error', content: 'Subject and description are required.' });
      return;
    }
    setSubmitting(true);
    try {
      await residentPortal.createMaintenanceRequest(token, {
        subject: requestForm.subject.trim(),
        description: requestForm.description.trim(),
        priority: requestForm.priority,
      });
      setFlash({ type: 'success', content: 'Maintenance request submitted.' });
      setRequestModal(false);
      const res = await residentPortal.listMaintenanceRequests(token);
      setTickets(res.data);
    } catch (err: unknown) {
      setFlash({ type: 'error', content: errorDetail(err, 'Failed to submit maintenance request.') });
    } finally {
      setSubmitting(false);
    }
  };

  const refreshPaymentState = async () => {
    const [balanceRes, methodsRes, leasesRes] = await Promise.all([
      residentPortal.getBalance(token),
      residentPortal.listPaymentMethods(token),
      residentPortal.listLeases(token),
    ]);
    setBalance(balanceRes.data);
    setPaymentMethods(methodsRes.data);
    setLeases(leasesRes.data);
  };

  const openPay = () => {
    setPayAmount(balance?.balance_due ?? '0');
    setPayMethodId(
      paymentMethods.find((m) => m.is_default && m.status === 'active')?.id ??
        paymentMethods.find((m) => m.status === 'active')?.id ??
        null,
    );
    // New key per attempt, reused across retries of that attempt.
    setPayKey(crypto.randomUUID());
    setPayModal(true);
  };

  const handlePay = async () => {
    const amount = Number(payAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setFlash({ type: 'error', content: 'Enter a payment amount greater than zero.' });
      return;
    }
    setPaying(true);
    try {
      const selectedMethod = paymentMethods.find((method) => method.id === payMethodId);
      if (!selectedMethod) {
        setFlash({ type: 'error', content: 'Select a saved payment method.' });
        return;
      }
      const res = await residentPortal.makePayment(token, {
        amount: payAmount,
        payment_method_id: payMethodId,
        method: selectedMethod.method_type,
        idempotency_key: payKey,
      });
      setBalance(res.data.balance);
      setPayModal(false);
      if (res.data.processor_status === 'unconfigured') {
        setFlash({
          type: 'error',
          content:
            'Online payments are not switched on for this property yet. Your payment was recorded as pending and no money has been taken. Please contact management to complete it.',
        });
      } else if (res.data.processor_status === 'processing') {
        setFlash({
          type: 'success',
          content: 'Bank payment submitted. Your balance will update after settlement.',
        });
      } else {
        setFlash({ type: 'success', content: 'Payment received. Thank you.' });
      }
      await refreshPaymentState();
    } catch (err: unknown) {
      setFlash({ type: 'error', content: errorDetail(err, 'Your payment could not be processed.') });
    } finally {
      setPaying(false);
    }
  };

  const handleConnectBank = async () => {
    if (!bankConsent) {
      setBankError('Accept the bank-link authorization before continuing.');
      return;
    }
    setBankBusy(true);
    setBankError(null);
    try {
      const link = await residentPortal.createAchLinkToken(token, true);
      const result = await openPlaidLink(link.data.link_token);
      if (!result) return;
      const selectedAccountId = result.metadata.accounts?.[0]?.id;
      if (!selectedAccountId) {
        throw new Error('Select one bank account in Plaid Link.');
      }
      await residentPortal.exchangeAch(token, {
        public_token: result.publicToken,
        account_id: selectedAccountId,
        institution_name: result.metadata.institution?.name ?? null,
        is_default: paymentMethods.length === 0,
        consent_accepted: true,
      });
      setBankModal(false);
      setBankConsent(false);
      setFlash({ type: 'success', content: 'Bank account connected.' });
      await refreshPaymentState();
    } catch (err: unknown) {
      setBankError(errorDetail(err, err instanceof Error ? err.message : 'Failed to connect bank account.'));
    } finally {
      setBankBusy(false);
    }
  };

  const handleDeleteMethod = async (id: string) => {
    try {
      await residentPortal.deletePaymentMethod(token, id);
      setFlash({ type: 'success', content: 'Payment method removed.' });
      await refreshPaymentState();
    } catch (err: unknown) {
      setFlash({ type: 'error', content: errorDetail(err, 'Failed to remove payment method.') });
    }
  };

  const handleAutopay = async (enabled: boolean, leaseId: string, methodId: string | null) => {
    if (enabled && !methodId) {
      setFlash({ type: 'error', content: 'Save a payment method before turning on autopay.' });
      return;
    }
    setAutopayBusy(true);
    try {
      await residentPortal.updateAutopay(token, {
        enabled,
        payment_method_id: enabled ? methodId : null,
        lease_id: leaseId,
        recurring_consent_accepted: enabled && recurringConsent,
      });
      setFlash({
        type: 'success',
        content: enabled ? 'Autopay is on.' : 'Autopay is off.',
      });
      await refreshPaymentState();
    } catch (err: unknown) {
      setFlash({ type: 'error', content: errorDetail(err, 'Failed to update autopay.') });
    } finally {
      setAutopayBusy(false);
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
    return <PortalAccessDenied />;
  }

  const residentName = profile ? `${profile.first_name} ${profile.last_name}`.trim() : '…';
  const currency = balance?.currency ?? leases[0]?.currency ?? 'USD';
  const activeLease = leases.find((l) => l.status === 'active' || l.status === 'pending') ?? leases[0] ?? null;
  const balanceDue = Number(balance?.balance_due ?? 0);
  const methodOptions = paymentMethods
    .filter((m) => m.status === 'active')
    .map((m) => ({ label: methodLabel(m), value: m.id }));
  const autopayMethodOptions = paymentMethods
    .filter((m) => m.status === 'active' && m.method_type === 'ach')
    .map((m) => ({ label: methodLabel(m), value: m.id }));
  const autopayMethodId =
    activeLease?.autopay_payment_method_id ??
    autopaySelection ??
    paymentMethods.find((m) => m.is_default && m.status === 'active' && m.method_type === 'ach')?.id ??
    paymentMethods.find((m) => m.status === 'active' && m.method_type === 'ach')?.id ??
    null;
  const autopayMethod = paymentMethods.find((m) => m.id === autopayMethodId);
  const stripeAvailable = Boolean(
    paymentConfig?.configured &&
      paymentConfig.provider.toLowerCase() === 'stripe' &&
      stripePromise,
  );
  const paymentUnavailableMessage = paymentConfigError
    ? 'Secure card entry is temporarily unavailable because payment configuration could not be loaded.'
    : paymentConfig && paymentConfig.provider.toLowerCase() !== 'stripe'
      ? `Adding cards in the portal is unavailable for the configured ${paymentConfig.provider} provider.`
      : paymentConfig && !paymentConfig.configured
        ? 'Online card setup is not configured for this property. Please contact management.'
        : null;

  return (
    <ContentLayout
      header={
        <Header variant="h1" description={`Resident portal for ${residentName}`}>
          Resident Portal
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
                  <Container
                    header={
                      <Header
                        variant="h2"
                        actions={
                          <Button
                            variant="primary"
                            disabled={balanceDue <= 0}
                            onClick={openPay}
                          >
                            Make a payment
                          </Button>
                        }
                      >
                        Account summary
                      </Header>
                    }
                  >
                    <ColumnLayout columns={3} variant="text-grid">
                      <div>
                        <Box variant="awsui-key-label">Monthly rent</Box>
                        <Box variant="awsui-value-large">
                          {formatMoney(balance?.monthly_rent, currency)}
                        </Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Security deposit</Box>
                        <Box variant="awsui-value-large">
                          {formatMoney(balance?.security_deposit, currency)}
                        </Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Balance due</Box>
                        <Box variant="awsui-value-large">
                          {formatMoney(balance?.balance_due, currency)}
                        </Box>
                      </div>
                    </ColumnLayout>
                  </Container>
                  <Container header={<Header variant="h2">Profile</Header>}>
                    <ColumnLayout columns={2} variant="text-grid">
                      <div>
                        <Box variant="awsui-key-label">Name</Box>
                        <div>{residentName || '—'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Status</Box>
                        <div>{profile?.status ?? '—'}</div>
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
              id: 'payments',
              label: 'Payments',
              content: (
                <SpaceBetween size="l">
                  <Container
                    header={
                      <Header
                        variant="h2"
                        description="Pay your rent balance online."
                        actions={
                          <Button variant="primary" disabled={balanceDue <= 0} onClick={openPay}>
                            Make a payment
                          </Button>
                        }
                      >
                        Balance due
                      </Header>
                    }
                  >
                    <SpaceBetween size="m">
                      <Box variant="awsui-value-large">
                        {formatMoney(balance?.balance_due, currency)}
                      </Box>
                      {balanceDue <= 0 && (
                        <Alert type="success">You are all paid up. Nothing is due right now.</Alert>
                      )}
                      {paymentMethods.length === 0 && (
                        <Alert type="info">
                          Add a payment method to pay online or turn on autopay.
                        </Alert>
                      )}
                    </SpaceBetween>
                  </Container>

                  <Container
                    header={
                      <Header
                        variant="h2"
                        actions={
                          <SpaceBetween direction="horizontal" size="xs">
                            <Button
                              iconName="add-plus"
                              disabled={!stripeAvailable}
                              onClick={() => setMethodModal(true)}
                            >
                              Add card
                            </Button>
                            <Button
                              disabled={!paymentConfig?.plaid_ach_available}
                              onClick={() => {
                                setBankError(null);
                                setBankModal(true);
                              }}
                            >
                              Connect bank account
                            </Button>
                          </SpaceBetween>
                        }
                      >
                        Saved payment methods
                      </Header>
                    }
                  >
                    {paymentUnavailableMessage && (
                      <Box margin={{ bottom: 'm' }}>
                        <Alert type="warning">{paymentUnavailableMessage}</Alert>
                      </Box>
                    )}
                    {paymentConfig && !paymentConfig.plaid_ach_available && (
                      <Box margin={{ bottom: 'm' }}>
                        <Alert type="info">
                          Bank account connection is unavailable for this property.
                        </Alert>
                      </Box>
                    )}
                    <Table
                      items={paymentMethods}
                      empty={
                        <Box textAlign="center" color="inherit">
                          No saved payment methods.
                        </Box>
                      }
                      columnDefinitions={[
                        {
                          id: 'method',
                          header: 'Method',
                          cell: (m: ResidentPortalPaymentMethod) => methodLabel(m),
                        },
                        {
                          id: 'default',
                          header: 'Default',
                          cell: (m: ResidentPortalPaymentMethod) =>
                            m.is_default ? <Badge color="green">Default</Badge> : '—',
                          width: 120,
                        },
                        {
                          id: 'added',
                          header: 'Added',
                          cell: (m: ResidentPortalPaymentMethod) => formatDate(m.created_at),
                          width: 140,
                        },
                        {
                          id: 'actions',
                          header: '',
                          cell: (m: ResidentPortalPaymentMethod) => (
                            <Button variant="link" onClick={() => handleDeleteMethod(m.id)}>
                              Remove
                            </Button>
                          ),
                          width: 110,
                        },
                      ]}
                    />
                  </Container>

                  <Container
                    header={
                      <Header
                        variant="h2"
                        description="Debit finalized rent invoices automatically on or after their due date."
                      >
                        Autopay
                      </Header>
                    }
                  >
                    {activeLease ? (
                      <SpaceBetween size="s">
                        {!activeLease.autopay_enabled && (
                          <FormField label="Autopay bank account">
                            <Select
                              selectedOption={autopayMethodOptions.find((option) => option.value === autopayMethodId) ?? null}
                              options={autopayMethodOptions}
                              placeholder="Connect or select a bank account"
                              empty="No active bank account is connected."
                              onChange={({ detail }) => setAutopaySelection(detail.selectedOption.value ?? null)}
                            />
                          </FormField>
                        )}
                        {autopayMethod?.method_type === 'ach' && !activeLease.autopay_enabled && (
                          <Checkbox
                            checked={recurringConsent}
                            onChange={({ detail }) => setRecurringConsent(detail.checked)}
                          >
                            I authorize recurring ACH debits for amounts due under my lease until I disable autopay or revoke authorization.
                          </Checkbox>
                        )}
                        <Toggle
                          checked={activeLease.autopay_enabled}
                          disabled={
                            autopayBusy ||
                            (!activeLease.autopay_enabled && !autopayMethodId) ||
                            (!activeLease.autopay_enabled && autopayMethod?.method_type === 'ach' && !recurringConsent)
                          }
                          onChange={({ detail }) =>
                            handleAutopay(detail.checked, activeLease.id, autopayMethodId)
                          }
                        >
                          {activeLease.autopay_enabled
                            ? `Autopay is on${
                                autopayMethodId
                                  ? ` using ${
                                      methodOptions.find((o) => o.value === autopayMethodId)?.label ??
                                      'your saved method'
                                    }`
                                  : ''
                              }`
                            : 'Autopay is off'}
                        </Toggle>
                        {activeLease.autopay_enabled && !activeLease.autopay_last_status && (
                          <Box color="text-status-inactive">
                            No scheduled debit has run yet. Autopay checks due rent each morning.
                          </Box>
                        )}
                        {activeLease.autopay_last_status && (
                          <Alert
                            type={
                              activeLease.autopay_last_status === 'succeeded'
                                ? 'success'
                                : activeLease.autopay_last_status === 'processing'
                                  ? 'info'
                                  : 'warning'
                            }
                            header={
                              activeLease.autopay_last_status === 'succeeded'
                                ? 'Latest scheduled debit settled'
                                : activeLease.autopay_last_status === 'processing'
                                  ? 'Latest scheduled debit is processing'
                                  : activeLease.autopay_last_status === 'returned'
                                    ? 'Latest scheduled debit was returned'
                                    : 'Latest scheduled debit failed'
                            }
                          >
                            {activeLease.autopay_last_attempt_at
                              ? `Attempted ${formatDate(activeLease.autopay_last_attempt_at)}. `
                              : ''}
                            {activeLease.autopay_last_detail ??
                              (activeLease.autopay_last_status === 'processing'
                                ? 'Your balance will update after bank settlement.'
                                : 'Review your saved bank account before the next rent due date.')}
                          </Alert>
                        )}
                      </SpaceBetween>
                    ) : (
                      <Box color="text-status-inactive">No lease on file.</Box>
                    )}
                  </Container>
                </SpaceBetween>
              ),
            },
            {
              id: 'leases',
              label: `Leases (${leases.length})`,
              content: (
                <Table
                  items={leases}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No leases on file.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'unit',
                      header: 'Unit',
                      cell: (l: ResidentPortalLease) =>
                        l.unit_number || l.unit_name || l.name || '—',
                    },
                    {
                      id: 'status',
                      header: 'Status',
                      cell: (l: ResidentPortalLease) => (
                        <Badge color={l.status === 'active' ? 'green' : 'grey'}>{l.status}</Badge>
                      ),
                      width: 120,
                    },
                    {
                      id: 'start',
                      header: 'Start',
                      cell: (l: ResidentPortalLease) => formatDate(l.start_date),
                    },
                    {
                      id: 'end',
                      header: 'End',
                      cell: (l: ResidentPortalLease) => formatDate(l.end_date),
                    },
                    {
                      id: 'rent',
                      header: 'Rent',
                      cell: (l: ResidentPortalLease) =>
                        `${formatMoney(l.rent_amount, l.currency)} / ${l.rent_frequency}`,
                    },
                    {
                      id: 'deposit',
                      header: 'Deposit',
                      cell: (l: ResidentPortalLease) => formatMoney(l.security_deposit, l.currency),
                    },
                  ]}
                />
              ),
            },
            {
              id: 'maintenance',
              label: `Maintenance (${tickets.length})`,
              content: (
                <SpaceBetween size="m">
                  <Box float="right">
                    <Button variant="primary" iconName="add-plus" onClick={openRequest}>
                      New request
                    </Button>
                  </Box>
                  <Table
                    items={tickets}
                    empty={
                      <Box textAlign="center" color="inherit">
                        No maintenance requests yet.
                      </Box>
                    }
                    columnDefinitions={[
                      { id: 'subject', header: 'Subject', cell: (t: ResidentPortalTicket) => t.subject },
                      {
                        id: 'priority',
                        header: 'Priority',
                        cell: (t: ResidentPortalTicket) => (
                          <Badge color={priorityColor(t.priority)}>{t.priority}</Badge>
                        ),
                        width: 110,
                      },
                      {
                        id: 'status',
                        header: 'Status',
                        cell: (t: ResidentPortalTicket) => (
                          <Badge color={ticketStatusColor(t.status)}>{t.status}</Badge>
                        ),
                        width: 130,
                      },
                      {
                        id: 'created',
                        header: 'Submitted',
                        cell: (t: ResidentPortalTicket) => formatDate(t.created_at),
                        width: 140,
                      },
                    ]}
                  />
                </SpaceBetween>
              ),
            },
            {
              id: 'documents',
              label: `Documents (${documents.length})`,
              content: (
                <Table
                  items={documents}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No documents available.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'name',
                      header: 'File',
                      cell: (d: Attachment) => d.original_filename,
                    },
                    {
                      id: 'size',
                      header: 'Size',
                      cell: (d: Attachment) => formatBytes(d.file_size),
                      width: 120,
                    },
                    {
                      id: 'created',
                      header: 'Added',
                      cell: (d: Attachment) => formatDate(d.created_at),
                      width: 140,
                    },
                  ]}
                />
              ),
            },
            {
              id: 'announcements',
              label: `Announcements (${announcements.length})`,
              content: (
                <Table
                  items={announcements}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No announcements.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'title',
                      header: 'Title',
                      cell: (a: ResidentPortalAnnouncement) => a.title,
                    },
                    {
                      id: 'body',
                      header: 'Message',
                      cell: (a: ResidentPortalAnnouncement) => a.body,
                    },
                    {
                      id: 'sent',
                      header: 'Sent',
                      cell: (a: ResidentPortalAnnouncement) => formatDate(a.sent_at),
                      width: 140,
                    },
                    {
                      id: 'read',
                      header: 'Read',
                      cell: (a: ResidentPortalAnnouncement) =>
                        a.read_at ? <Badge color="green">Read</Badge> : <Badge color="blue">New</Badge>,
                      width: 100,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </SpaceBetween>

      <Modal
        visible={requestModal}
        onDismiss={() => setRequestModal(false)}
        header="New maintenance request"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setRequestModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={submitting} onClick={handleSubmitRequest}>
                Submit
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Subject">
            <Input
              value={requestForm.subject}
              onChange={({ detail }) =>
                setRequestForm((f) => ({ ...f, subject: detail.value }))
              }
              placeholder="e.g. Leaking faucet in kitchen"
            />
          </FormField>
          <FormField label="Description">
            <Textarea
              value={requestForm.description}
              onChange={({ detail }) =>
                setRequestForm((f) => ({ ...f, description: detail.value }))
              }
              placeholder="Describe the issue in detail"
            />
          </FormField>
          <FormField label="Priority">
            <Select
              selectedOption={
                PRIORITY_OPTIONS.find((o) => o.value === requestForm.priority) ?? PRIORITY_OPTIONS[1]
              }
              options={PRIORITY_OPTIONS}
              onChange={({ detail }) =>
                setRequestForm((f) => ({ ...f, priority: detail.selectedOption.value ?? 'medium' }))
              }
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={bankModal}
        onDismiss={() => setBankModal(false)}
        header="Connect bank account"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setBankModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={bankBusy} disabled={!bankConsent} onClick={handleConnectBank}>
                Continue to Plaid
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Alert type="info">
            Plaid securely links your selected bank account. Office Manager never receives your bank credentials, account number, or routing number.
          </Alert>
          {bankError && <Alert type="error">{bankError}</Alert>}
          <Checkbox checked={bankConsent} onChange={({ detail }) => setBankConsent(detail.checked)}>
            I authorize this property manager and its payment processor to link my selected bank account for resident payments. Saving an account does not initiate a debit.
          </Checkbox>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={payModal}
        onDismiss={() => setPayModal(false)}
        header="Make a payment"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setPayModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={paying} onClick={handlePay}>
                Pay {formatMoney(payAmount, currency)}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box>
            Balance due: <strong>{formatMoney(balance?.balance_due, currency)}</strong>
          </Box>
          <FormField
            label="Amount"
            description="Defaults to your full balance. You can pay part of it instead."
          >
            <Input
              type="number"
              inputMode="decimal"
              value={payAmount}
              onChange={({ detail }) => setPayAmount(detail.value)}
            />
          </FormField>
          <FormField label="Payment method">
            {paymentMethods.length > 0 ? (
              <Select
                selectedOption={methodOptions.find((o) => o.value === payMethodId) ?? null}
                options={methodOptions}
                placeholder="Select a saved method"
                onChange={({ detail }) => setPayMethodId(detail.selectedOption.value ?? null)}
              />
            ) : (
              <Alert type="info">
                You have no saved payment methods. Add one from the Payments tab first.
              </Alert>
            )}
          </FormField>
        </SpaceBetween>
      </Modal>

      {stripePromise && (
        <Elements stripe={stripePromise}>
          <AddPaymentMethodModal
            visible={methodModal}
            token={token}
            isDefault={paymentMethods.length === 0}
            onDismiss={() => setMethodModal(false)}
            onSaved={refreshPaymentState}
            setFlash={setFlash}
          />
        </Elements>
      )}
    </ContentLayout>
  );
};

export default ResidentPortalPage;
