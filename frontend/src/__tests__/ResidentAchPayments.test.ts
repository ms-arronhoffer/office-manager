import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const page = source('src/pages/ResidentPortalPage.tsx');
const api = source('src/api/index.ts');

describe('resident Plaid ACH payment security surface', () => {
  it('requires bank-link consent before opening Plaid', () => {
    expect(page).toContain('disabled={!bankConsent}');
    expect(page.indexOf('if (!bankConsent)')).toBeLessThan(
      page.indexOf('openPlaidLink(link.data.link_token)'),
    );
  });

  it('uses the selected Link account and labels ACH separately from cards', () => {
    expect(page).toContain('result.metadata.accounts?.[0]?.id');
    expect(page).toContain('account_id: selectedAccountId');
    expect(page).toContain("m.method_type === 'ach'");
    expect(page).toContain('ending ${m.last4}');
    expect(page).toContain('method: selectedMethod.method_type');
  });

  it('shows pending settlement and requires separate recurring authorization', () => {
    expect(page).toContain("res.data.processor_status === 'processing'");
    expect(page).toContain('Your balance will update after settlement.');
    expect(page).toContain('recurring_consent_accepted: enabled && recurringConsent');
    expect(page).toContain('disabled={!paymentConfig?.plaid_ach_available}');
  });

  it('limits scheduled autopay to bank accounts and shows execution status', () => {
    expect(page).toContain("m.method_type === 'ach'");
    expect(page).toContain('Autopay bank account');
    expect(page).toContain('autopay_last_status');
    expect(page).toContain('Latest scheduled debit settled');
    expect(page).toContain('Autopay checks due rent each morning.');
  });

  it('does not collect bank or routing numbers', () => {
    expect(page).not.toMatch(/account_number|routing_number/i);
    expect(api).not.toMatch(/account_number|routing_number/i);
  });
});
