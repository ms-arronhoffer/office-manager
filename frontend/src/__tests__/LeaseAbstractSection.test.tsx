import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const getAbstract = vi.fn();
const updateAbstractClause = vi.fn();

vi.mock('@/api', () => ({
  leases: {
    getAbstract: (...args: unknown[]) => getAbstract(...args),
    updateAbstractClause: (...args: unknown[]) => updateAbstractClause(...args),
  },
}));

const addFlash = vi.fn();
vi.mock('@/context/FlashbarContext', () => ({
  useFlashbar: () => ({ addFlash, removeFlash: vi.fn() }),
}));

const { default: LeaseAbstractSection } = await import(
  '@/components/common/LeaseAbstractSection'
);

const SAMPLE = {
  lease_id: 'lease-1',
  clauses: [
    {
      category_key: 'security_deposit',
      name: 'Security Deposit',
      group: 'rights',
      order: 20,
      status: 'incomplete',
      content: { deposit_amount: 5000 },
      notes: null,
      updated_at: null,
      fields: [
        { key: 'deposit_amount', label: 'Deposit Amount', type: 'currency' },
        { key: 'deposit_type', label: 'Deposit Type', type: 'select', options: ['cash', 'guarantee'] },
        { key: 'summary', label: 'Summary', type: 'textarea' },
        { key: 'notes', label: 'Notes', type: 'textarea' },
      ],
    },
    {
      category_key: 'force_majeure',
      name: 'Force Majeure',
      group: 'clauses',
      order: 10,
      status: 'needs_content',
      content: null,
      notes: null,
      updated_at: null,
      fields: [
        { key: 'summary', label: 'Summary', type: 'textarea' },
        { key: 'notes', label: 'Notes', type: 'textarea' },
      ],
    },
  ],
  summary: { total: 2, contains_content: 0, needs_content: 1, incomplete: 1 },
};

beforeEach(() => {
  getAbstract.mockReset();
  updateAbstractClause.mockReset();
  addFlash.mockReset();
});

describe('LeaseAbstractSection', () => {
  it('renders the clause grid with completeness statuses', async () => {
    getAbstract.mockResolvedValue({ data: SAMPLE });
    render(<LeaseAbstractSection leaseId="lease-1" canEdit={true} />);

    await waitFor(() => {
      expect(screen.getByText('Security Deposit')).toBeInTheDocument();
    });
    expect(screen.getByText('Force Majeure')).toBeInTheDocument();
    // Header roll-up counter shows contains/total.
    expect(screen.getByText('(0/2)')).toBeInTheDocument();
    // Legend present.
    expect(screen.getByText('Contains Content')).toBeInTheDocument();
    expect(screen.getByText('Needs Content')).toBeInTheDocument();
  });

  it('opens the edit modal and saves a clause', async () => {
    getAbstract.mockResolvedValue({ data: SAMPLE });
    updateAbstractClause.mockResolvedValue({
      data: { ...SAMPLE.clauses[0], status: 'contains_content' },
    });
    render(<LeaseAbstractSection leaseId="lease-1" canEdit={true} />);

    await waitFor(() => screen.getByText('Security Deposit'));

    fireEvent.click(screen.getByLabelText('Edit Security Deposit'));

    // Modal renders the schema fields (excluding the standalone Notes field row).
    await waitFor(() => expect(screen.getByText('Deposit Amount')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => expect(updateAbstractClause).toHaveBeenCalledTimes(1));
    expect(updateAbstractClause).toHaveBeenCalledWith(
      'lease-1',
      'security_deposit',
      expect.objectContaining({ content: { deposit_amount: 5000 } }),
    );
    expect(addFlash).toHaveBeenCalled();
  });

  it('hides edit controls when canEdit is false', async () => {
    getAbstract.mockResolvedValue({ data: SAMPLE });
    render(<LeaseAbstractSection leaseId="lease-1" canEdit={false} />);

    await waitFor(() => screen.getByText('Security Deposit'));
    expect(screen.queryByLabelText('Edit Security Deposit')).not.toBeInTheDocument();
  });
});
