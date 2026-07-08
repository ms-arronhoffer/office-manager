// Lease lifecycle status codes and their display labels. Kept in one place so
// the lease form drop-down and the Leases table filter/column stay in sync with
// the backend LEASE_STATUSES enum (see backend/app/schemas/lease.py).

export interface LeaseStatusOption {
  label: string;
  value: string;
}

export const LEASE_STATUS_OPTIONS: LeaseStatusOption[] = [
  { label: 'Active', value: 'active' },
  { label: 'Pending', value: 'pending' },
  { label: 'In Negotiation', value: 'in_negotiation' },
  { label: 'Renewed', value: 'renewed' },
  { label: 'Month-to-Month', value: 'month_to_month' },
  { label: 'Holdover', value: 'holdover' },
  { label: 'Expired', value: 'expired' },
  { label: 'Terminated', value: 'terminated' },
  { label: 'Cancelled', value: 'cancelled' },
];

const LEASE_STATUS_LABELS: Record<string, string> = LEASE_STATUS_OPTIONS.reduce(
  (acc, opt) => {
    acc[opt.value] = opt.label;
    return acc;
  },
  {} as Record<string, string>,
);

/** Human-readable label for a lease status code (falls back to the raw value). */
export function leaseStatusLabel(value?: string | null): string {
  if (!value) return '';
  return LEASE_STATUS_LABELS[value] ?? value;
}
