import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(join(process.cwd(), 'src/pages/ConnectorsPage.tsx'), 'utf8');

describe('tenant integration configuration surface', () => {
  it('defensively removes Platform Stripe from readiness', () => {
    expect(source).toContain("item.provider !== 'platform_stripe'");
    expect(source).not.toContain('Platform Stripe row');
  });

  it.each(['resident_payments', 'screening', 'plaid'])('offers configuration for %s', (provider) => {
    expect(source).toContain(`'${provider}'`);
  });

  it('keeps secret fields masked and provides tenant save and disconnect actions', () => {
    expect(source).toContain('type="password"');
    expect(source).toContain('Save to tenant');
    expect(source).toContain('Disconnect');
  });

  it('configures resident ACH and tenant Stripe settlement webhooks', () => {
    expect(source).toContain('Enable resident ACH bank linking');
    expect(source).toContain('webhook_secret:');
    expect(source).toContain('/api/v1/resident-payments/stripe/webhook/');
    expect(source).toContain('charge.succeeded');
    expect(source).toContain('charge.dispute.created');
  });
});