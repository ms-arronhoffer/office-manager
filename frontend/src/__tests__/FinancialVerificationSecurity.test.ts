import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const page = source('src/pages/FinancialVerificationPage.tsx');
const api = source('src/api/index.ts');
const staff = source('src/pages/LeasingFunnelPage.tsx');

describe('applicant financial verification security surface', () => {
  it('requires explicit consent before Plaid Link and scrubs the magic-link token', () => {
    expect(page).toContain("const [accepted, setAccepted] = useState(false)");
    expect(page).toContain('disabled={!accepted}');
    expect(page.indexOf('financialVerificationPublic.consent()')).toBeLessThan(
      page.indexOf('openPlaidLink(consent.data.link_token)'),
    );
    expect(page).toContain("window.history.replaceState(null, '', '/financial-verify')");
    expect(api).toContain('withCredentials: true');
  });

  it('does not render account or routing numbers or transaction rows', () => {
    expect(page).not.toMatch(/routing_number|account_number|transaction_rows|transaction_description/i);
    expect(staff).not.toMatch(/routing_number|account_number|transaction_rows|transaction_description/i);
    expect(page).toContain('Account and routing numbers, raw identity details, and transaction rows are not retained.');
    expect(staff).toContain('Aggregate available balance');
    expect(staff).toContain('Decision support recommendation');
  });

  it('keeps Plaid financial verification separate from background screening', () => {
    expect(staff).toContain('Background screening');
    expect(staff).toContain('Financial verification (Plaid)');
    expect(staff).toContain('It is separate from background screening');
  });
});