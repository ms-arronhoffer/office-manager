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
    features: ['Up to 10 offices', 'Up to 100 active leases', 'Unlimited users', 'Maintenance ticket tracking', 'Basic reporting & CSV export', '90-day audit log'],
    cta: 'Subscribe to Starter',
  },
  {
    plan: 'pro',
    price: '$399 / month',
    features: ['Up to 50 offices', 'Up to 500 active leases', 'Unlimited users', 'HVAC & advanced SLA rules', 'Advanced analytics & PDF export', 'AI abstracts & digital waivers', 'Full audit log (unlimited)'],
    cta: 'Upgrade to Pro',
  },
  {
    plan: 'enterprise',
    price: 'Contact us',
    features: ['Everything in Pro', 'SSO / SAML', 'Custom fields', 'API access', 'Dedicated support', 'Custom contracts'],
    cta: null,
  },
];

const PLAN_RANK: Record<string, number> = { starter: 0, pro: 1, enterprise: 2 };

const BillingPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [sub, setSub] = useState<BillingSubscription | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isChangingPlan, setIsChangingPlan] = useState<string | null>(null);
  const [isOpeningPortal, setIsOpeningPortal] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isReactivating, setIsReactivating] = useState(false);
  const [checkoutSuccess, setCheckoutSuccess] = useState(false);
  const [planChangeSuccess, setPlanChangeSuccess] = useState(false);

  const refreshSubscription = async () => {
    const { data } = await billingApi.getSubscription();
    setSub(data);
    return data;
  };

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
        await refreshSubscription();
      } catch {
        setError('Could not load billing information.');
      } finally {
        setIsLoading(false);
      }
    };

    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlePlanChange = async (plan: 'starter' | 'pro') => {
    setIsChangingPlan(plan);
    setError(null);
    try {
      const { data } = await billingApi.createCheckout(plan);
      if (data.checkout_url) {
        // No existing subscription yet — redirect to Stripe Checkout.
        window.location.href = data.checkout_url;
        return;
      }
      // Existing subscription was switched in place; refresh and show success.
      await refreshSubscription();
      setPlanChangeSuccess(true);
    } catch {
      setError('Could not change plan. Please try again.');
    } finally {
      setIsChangingPlan(null);
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

  const handleCancelSubscription = async () => {
    setIsCancelling(true);
    setError(null);
    try {
      await billingApi.cancelSubscription();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Could not cancel subscription. Please try again.');
      setIsCancelling(false);
      return;
    }
    // Cancellation succeeded — a follow-up refresh failure must not be
    // reported as a cancel failure.
    try {
      await refreshSubscription();
    } catch {
      /* best-effort — the next page load will reflect the latest state */
    }
    setIsCancelling(false);
  };

  const handleReactivateSubscription = async () => {
    setIsReactivating(true);
    setError(null);
    try {
      await billingApi.reactivateSubscription();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Could not reactivate subscription. Please try again.');
      setIsReactivating(false);
      return;
    }
    try {
      await refreshSubscription();
    } catch {
      /* best-effort — the next page load will reflect the latest state */
    }
    setIsReactivating(false);
  };

  if (isLoading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  const currentPlan = sub?.plan ?? 'starter';
  // The org has a live paid subscription only once Stripe has one on file and it
  // hasn't been canceled. Until then (including the whole free-trial window) the
  // customer should be able to subscribe to *either* Starter or Pro — even to the
  // Starter plan they are currently trialing on.
  const hasPaidSubscription = !!sub?.stripe_subscription_id && sub?.payment_status !== 'canceled';

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

        {planChangeSuccess && (
          <Alert type="success" dismissible onDismiss={() => setPlanChangeSuccess(false)}>
            Your plan has been updated.
          </Alert>
        )}

        {sub && !sub.billing_configured && (
          <Alert type="info">
            Billing is not configured on this server. Set{' '}
            <code>STRIPE_SECRET_KEY</code> and related environment variables to enable payments.
          </Alert>
        )}

        {sub?.is_trialing && (
          <Alert type="info" header="You're on a free trial">
            {sub.trial_days_remaining != null && sub.trial_days_remaining > 0
              ? `${sub.trial_days_remaining} day${sub.trial_days_remaining === 1 ? '' : 's'} remaining in your trial`
              : 'Your trial ends today'}
            {sub.trial_ends_at && ` (ends ${new Date(sub.trial_ends_at).toLocaleDateString()}).`}
            {' '}Subscribe to a plan below to keep uninterrupted access after your trial ends.
          </Alert>
        )}

        {sub?.cancel_at_period_end && (
          <Alert
            type="warning"
            header="Subscription scheduled to cancel"
            action={
              <Button loading={isReactivating} onClick={handleReactivateSubscription}>
                Keep my subscription
              </Button>
            }
          >
            Your subscription has been canceled and will not renew.
            {sub.current_period_end
              ? ` You'll keep full access until ${new Date(sub.current_period_end).toLocaleDateString()}.`
              : ' You\'ll keep full access through the end of your current billing period.'}
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
          <Container
            header={
              <Header
                variant="h2"
                actions={
                  sub.stripe_subscription_id && !sub.cancel_at_period_end && sub.billing_configured ? (
                    <Button loading={isCancelling} onClick={handleCancelSubscription}>
                      Cancel subscription
                    </Button>
                  ) : undefined
                }
              >
                Current plan
              </Header>
            }
          >
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
                        : sub.is_trialing
                        ? 'blue'
                        : sub.is_active
                        ? 'green'
                        : 'red'
                    }
                  >
                    {sub.payment_status === 'past_due'
                      ? 'Past due'
                      : sub.is_trialing
                      ? 'Trial'
                      : sub.is_active
                      ? 'Active'
                      : 'Inactive'}
                  </Badge>
                </Box>
              </SpaceBetween>
              {sub.is_trialing && sub.trial_ends_at && (
                <SpaceBetween size="xs">
                  <Box variant="awsui-key-label">Trial ends</Box>
                  <Box>{new Date(sub.trial_ends_at).toLocaleDateString()}</Box>
                </SpaceBetween>
              )}
              {sub.stripe_subscription_id && sub.current_period_end && (
                <SpaceBetween size="xs">
                  <Box variant="awsui-key-label">
                    {sub.cancel_at_period_end ? 'Access ends' : 'Renews'}
                  </Box>
                  <Box>{new Date(sub.current_period_end).toLocaleDateString()}</Box>
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
                  {hasPaidSubscription && item.plan === currentPlan && <Badge color="blue">Current</Badge>}
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
                  content: item => {
                    if (item.plan === 'enterprise') {
                      return <Box color="text-body-secondary">Custom pricing — contact sales</Box>;
                    }
                    if (!sub?.billing_configured) return null;

                    // During the trial (or any time before a paid subscription
                    // exists) offer a direct Subscribe button for both Starter
                    // and Pro — including the plan currently being trialed — so
                    // the customer can start paying whenever they choose.
                    if (!hasPaidSubscription) {
                      return (
                        <Button
                          variant={item.plan === 'pro' ? 'primary' : 'normal'}
                          loading={isChangingPlan === item.plan}
                          onClick={() => handlePlanChange(item.plan as 'starter' | 'pro')}
                          fullWidth
                        >
                          {`Subscribe to ${PLAN_LABELS[item.plan]}`}
                        </Button>
                      );
                    }

                    if (item.plan === currentPlan) {
                      return <Box color="text-status-success">Your current plan</Box>;
                    }
                    if (currentPlan === 'enterprise') {
                      return <Box color="text-body-secondary">Contact sales to change plans</Box>;
                    }
                    const isDowngrade = PLAN_RANK[item.plan] < PLAN_RANK[currentPlan];
                    const label = isDowngrade ? `Switch to ${PLAN_LABELS[item.plan]}` : item.cta;
                    return (
                      <Button
                        variant={!isDowngrade && item.plan === 'pro' ? 'primary' : 'normal'}
                        loading={isChangingPlan === item.plan}
                        onClick={() => handlePlanChange(item.plan as 'starter' | 'pro')}
                        fullWidth
                      >
                        {label}
                      </Button>
                    );
                  },
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
