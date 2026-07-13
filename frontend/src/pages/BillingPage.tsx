import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Cards from '@cloudscape-design/components/cards';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import { billing as billingApi } from '@/api';
import type { BillingSubscription } from '@/types';

const PLAN_LABELS: Record<string, string> = {
  starter: 'Starter',
  pro: 'Pro',
  enterprise: 'Enterprise',
};

const PLAN_COLOR: Record<string, 'grey' | 'blue' | 'green'> = {
  starter: 'grey',
  pro: 'blue',
  enterprise: 'green',
};

interface PlanCard {
  plan: 'starter' | 'pro' | 'enterprise';
  price: string;
  features: string[];
  cta: string | null;
}

const PLANS: PlanCard[] = [
  {
    plan: 'starter',
    price: '$99 / month',
    features: ['Up to 3 users', '1 office', 'Maintenance tickets', 'Basic reporting'],
    cta: null,
  },
  {
    plan: 'pro',
    price: '$399 / month',
    features: ['Unlimited users', 'Unlimited offices', 'Advanced analytics', 'SLA management', 'Email notifications', 'CSV exports'],
    cta: 'Upgrade to Pro',
  },
  {
    plan: 'enterprise',
    price: 'Contact us',
    features: ['Everything in Pro', 'SSO / SAML', 'Custom fields', 'API access', 'Dedicated support', 'Custom contracts'],
    cta: null,
  },
];

const BillingPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [sub, setSub] = useState<BillingSubscription | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isUpgrading, setIsUpgrading] = useState<string | null>(null);
  const [isOpeningPortal, setIsOpeningPortal] = useState(false);
  const [checkoutSuccess, setCheckoutSuccess] = useState(false);

  useEffect(() => {
    const sessionId = searchParams.get('session_id');

    const load = async () => {
      if (sessionId) {
        try {
          await billingApi.confirmCheckout(sessionId);
          setCheckoutSuccess(true);
        } catch {
          // Fall through — the webhook may still land shortly, and the
          // subscription fetch below will reflect the latest known state.
        } finally {
          // Drop session_id from the URL so a refresh doesn't re-confirm.
          searchParams.delete('session_id');
          setSearchParams(searchParams, { replace: true });
        }
      }

      try {
        const { data } = await billingApi.getSubscription();
        setSub(data);
      } catch {
        setError('Could not load billing information.');
      } finally {
        setIsLoading(false);
      }
    };

    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleUpgrade = async (plan: 'pro') => {
    setIsUpgrading(plan);
    try {
      const { data } = await billingApi.createCheckout(plan);
      window.location.href = data.checkout_url;
    } catch {
      setError('Could not start checkout. Please try again.');
    } finally {
      setIsUpgrading(null);
    }
  };

  const handleManageBilling = async () => {
    setIsOpeningPortal(true);
    try {
      const { data } = await billingApi.createPortal();
      window.location.href = data.portal_url;
    } catch {
      setError('Could not open billing portal. Please try again.');
    } finally {
      setIsOpeningPortal(false);
    }
  };

  if (isLoading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  const currentPlan = sub?.plan ?? 'starter';

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Manage your organization's subscription and billing."
          actions={
            sub?.stripe_customer_id && sub.billing_configured ? (
              <Button
                variant="normal"
                loading={isOpeningPortal}
                onClick={handleManageBilling}
                iconName="external"
              >
                Manage billing
              </Button>
            ) : undefined
          }
        >
          Billing &amp; Plan
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        {checkoutSuccess && (
          <Alert type="success" dismissible onDismiss={() => setCheckoutSuccess(false)}>
            Payment successful — your plan has been updated.
          </Alert>
        )}

        {sub && !sub.billing_configured && (
          <Alert type="info">
            Billing is not configured on this server. Set{' '}
            <code>STRIPE_SECRET_KEY</code> and related environment variables to enable payments.
          </Alert>
        )}

        {sub?.payment_status === 'past_due' && (
          <Alert
            type="warning"
            header="Payment past due"
            action={
              sub.stripe_customer_id && sub.billing_configured ? (
                <Button loading={isOpeningPortal} onClick={handleManageBilling}>
                  Update payment method
                </Button>
              ) : undefined
            }
          >
            Your last payment failed. Please update your payment method to avoid service interruption.
            Stripe will retry automatically — no action needed if you&apos;ve already resolved this.
          </Alert>
        )}

        {/* Current plan summary */}
        {sub && (
          <Container header={<Header variant="h2">Current plan</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <SpaceBetween size="xs">
                <Box variant="awsui-key-label">Plan</Box>
                <Box>
                  <Badge color={PLAN_COLOR[currentPlan] ?? 'grey'}>
                    {PLAN_LABELS[currentPlan] ?? currentPlan}
                  </Badge>
                </Box>
              </SpaceBetween>
              <SpaceBetween size="xs">
                <Box variant="awsui-key-label">Seats used</Box>
                <Box>
                  {sub.seat_count}
                  {sub.max_seats != null ? ` / ${sub.max_seats}` : ' (unlimited)'}
                </Box>
              </SpaceBetween>
              <SpaceBetween size="xs">
                <Box variant="awsui-key-label">Status</Box>
                <Box>
                  <Badge
                    color={
                      sub.payment_status === 'past_due'
                        ? 'red'
                        : sub.is_active
                        ? 'green'
                        : 'red'
                    }
                  >
                    {sub.payment_status === 'past_due'
                      ? 'Past due'
                      : sub.is_active
                      ? 'Active'
                      : 'Inactive'}
                  </Badge>
                </Box>
              </SpaceBetween>
              {sub.trial_ends_at && (
                <SpaceBetween size="xs">
                  <Box variant="awsui-key-label">Trial ends</Box>
                  <Box>{new Date(sub.trial_ends_at).toLocaleDateString()}</Box>
                </SpaceBetween>
              )}
            </ColumnLayout>
          </Container>
        )}

        {/* Plan comparison */}
        <Container header={<Header variant="h2">Plans</Header>}>
          <Cards
            items={PLANS}
            cardDefinition={{
              header: item => (
                <SpaceBetween direction="horizontal" size="xs">
                  <span style={{ fontWeight: 600, fontSize: 16 }}>{PLAN_LABELS[item.plan]}</span>
                  {item.plan === currentPlan && <Badge color="blue">Current</Badge>}
                </SpaceBetween>
              ),
              sections: [
                {
                  id: 'price',
                  header: 'Price',
                  content: item => (
                    <Box variant="h3" color="text-status-info">
                      {item.price}
                    </Box>
                  ),
                },
                {
                  id: 'features',
                  header: 'Includes',
                  content: item => (
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {item.features.map(f => (
                        <li key={f} style={{ marginBottom: 4 }}>
                          {f}
                        </li>
                      ))}
                    </ul>
                  ),
                },
                {
                  id: 'action',
                  content: item =>
                    item.cta && item.plan !== currentPlan && sub?.billing_configured ? (
                      <Button
                        variant={item.plan === 'pro' ? 'primary' : 'normal'}
                        loading={isUpgrading === item.plan}
                        onClick={() => handleUpgrade(item.plan as 'pro')}
                        fullWidth
                        disabled={currentPlan === 'enterprise' && item.plan === 'pro'}
                      >
                        {item.cta}
                      </Button>
                    ) : item.plan === currentPlan ? (
                      <Box color="text-status-success">Your current plan</Box>
                    ) : item.plan === 'enterprise' ? (
                      <Box color="text-body-secondary">Custom pricing — contact sales</Box>
                    ) : null,
                },
              ],
            }}
            cardsPerRow={[{ cards: 1 }, { minWidth: 500, cards: 3 }]}
          />
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default BillingPage;
