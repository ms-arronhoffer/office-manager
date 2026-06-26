import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const searchLeaseDocuments = vi.fn();
const getLeaseDocumentText = vi.fn();
const reindexLeaseDocuments = vi.fn();

vi.mock('@/api', () => ({
  ai: {
    searchLeaseDocuments: (...args: unknown[]) => searchLeaseDocuments(...args),
    getLeaseDocumentText: (...args: unknown[]) => getLeaseDocumentText(...args),
    reindexLeaseDocuments: (...args: unknown[]) => reindexLeaseDocuments(...args),
  },
}));

const { default: LeaseDocumentSearch } = await import(
  '@/components/common/LeaseDocumentSearch'
);

const MATCHES = {
  query: 'base rent',
  matches: [
    {
      lease_id: 'lease-1',
      lease_name: 'Acme HQ',
      attachment_id: 'att-1',
      source_filename: 'lease.pdf',
      chunk_index: 0,
      snippet: 'Tenant shall pay base rent monthly.',
      score: 0.9,
      match_type: 'keyword',
    },
    {
      lease_id: 'lease-1',
      lease_name: 'Acme HQ',
      attachment_id: 'att-1',
      source_filename: 'lease.pdf',
      chunk_index: 1,
      snippet: 'Base rent escalates annually.',
      score: 0.5,
      match_type: 'keyword',
    },
  ],
};

const PREVIEW = {
  attachment_id: 'att-1',
  source_filename: 'lease.pdf',
  content_type: 'application/pdf',
  text: 'Article 2. The base rent is $10,000. Base rent escalates each year.',
  extractable: true,
};

beforeEach(() => {
  searchLeaseDocuments.mockReset();
  getLeaseDocumentText.mockReset();
  reindexLeaseDocuments.mockReset();
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn();
  }
});

describe('LeaseDocumentSearch', () => {
  it('shows matches and a highlighted preview pane after searching', async () => {
    searchLeaseDocuments.mockResolvedValue({ data: MATCHES });
    getLeaseDocumentText.mockResolvedValue({ data: PREVIEW });

    render(<LeaseDocumentSearch leaseId="lease-1" />);

    fireEvent.change(screen.getByPlaceholderText(/renewal option/i), {
      target: { value: 'base rent' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

    await waitFor(() => expect(searchLeaseDocuments).toHaveBeenCalledWith('lease-1', 'base rent'));
    // Two hits from the same document are both listed.
    expect(screen.getByText('2 matches')).toBeInTheDocument();
    // Preview text loads for the first (auto-selected) match.
    await waitFor(() => expect(getLeaseDocumentText).toHaveBeenCalledWith('lease-1', 'att-1'));
    await waitFor(() => expect(screen.getByText(/escalates each year/i)).toBeInTheDocument());
    // The query terms are highlighted; "base"/"rent" each appear twice → 4.
    await waitFor(() => expect(screen.getByText('1 of 4')).toBeInTheDocument());
  });

  it('renders a fallback message for non-extractable documents', async () => {
    searchLeaseDocuments.mockResolvedValue({ data: MATCHES });
    getLeaseDocumentText.mockResolvedValue({
      data: { ...PREVIEW, text: null, extractable: false },
    });

    render(<LeaseDocumentSearch leaseId="lease-1" />);
    fireEvent.change(screen.getByPlaceholderText(/renewal option/i), {
      target: { value: 'base rent' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

    await waitFor(() => expect(getLeaseDocumentText).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/can't be previewed as text/i)).toBeInTheDocument(),
    );
  });

  it('shows an empty state when there are no matches', async () => {
    searchLeaseDocuments.mockResolvedValue({ data: { query: 'zzz', matches: [] } });

    render(<LeaseDocumentSearch leaseId="lease-1" />);
    fireEvent.change(screen.getByPlaceholderText(/renewal option/i), {
      target: { value: 'zzz' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

    await waitFor(() =>
      expect(screen.getByText(/No matching text found/i)).toBeInTheDocument(),
    );
    expect(getLeaseDocumentText).not.toHaveBeenCalled();
  });
});
