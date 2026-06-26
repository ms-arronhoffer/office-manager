import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const searchLeaseDocuments = vi.fn();
const getLeaseDocumentText = vi.fn();
const reindexLeaseDocuments = vi.fn();
const listLeaseDocuments = vi.fn();

vi.mock('@/api', () => ({
  ai: {
    searchLeaseDocuments: (...args: unknown[]) => searchLeaseDocuments(...args),
    getLeaseDocumentText: (...args: unknown[]) => getLeaseDocumentText(...args),
    reindexLeaseDocuments: (...args: unknown[]) => reindexLeaseDocuments(...args),
    listLeaseDocuments: (...args: unknown[]) => listLeaseDocuments(...args),
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

const DOCUMENTS = {
  lease_id: 'lease-1',
  documents: [
    { attachment_id: 'att-1', source_filename: 'lease.pdf', chunk_count: 3 },
    { attachment_id: 'att-2', source_filename: 'amendment.pdf', chunk_count: 2 },
  ],
};

beforeEach(() => {
  searchLeaseDocuments.mockReset();
  getLeaseDocumentText.mockReset();
  reindexLeaseDocuments.mockReset();
  listLeaseDocuments.mockReset();
  listLeaseDocuments.mockResolvedValue({ data: DOCUMENTS });
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

    await waitFor(() =>
      expect(searchLeaseDocuments).toHaveBeenCalledWith('lease-1', 'base rent', 10, null),
    );
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

  it('scopes the search to a selected document', async () => {
    searchLeaseDocuments.mockResolvedValue({ data: { query: 'rent', matches: [] } });
    const user = userEvent.setup();

    render(<LeaseDocumentSearch leaseId="lease-1" />);

    // The document picker is populated from the indexed-documents endpoint.
    await waitFor(() => expect(listLeaseDocuments).toHaveBeenCalledWith('lease-1'));

    // Open the scope dropdown (its trigger shows the current selection) and
    // pick the second document.
    await user.click(screen.getByRole('button', { name: /All documents/i }));
    const option = await screen.findByText('amendment.pdf');
    await user.click(option);

    fireEvent.change(screen.getByPlaceholderText(/renewal option/i), {
      target: { value: 'rent' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

    // The chosen attachment id is passed through to the search request.
    await waitFor(() =>
      expect(searchLeaseDocuments).toHaveBeenCalledWith('lease-1', 'rent', 10, 'att-2'),
    );
  });
});
