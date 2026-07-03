import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

const { default: FileUploadField } = await import(
  '@/components/common/FileUploadField'
);

describe('FileUploadField', () => {
  it('renders the default label and deferred-upload constraint text', () => {
    render(<FileUploadField files={[]} onChange={vi.fn()} />);
    expect(screen.getByText('Attachments')).toBeInTheDocument();
    expect(
      screen.getByText('Optional — files will be uploaded after saving'),
    ).toBeInTheDocument();
  });

  it('honours a custom label', () => {
    render(
      <FileUploadField files={[]} onChange={vi.fn()} label="Lease documents" />,
    );
    expect(screen.getByText('Lease documents')).toBeInTheDocument();
  });

  it('lists the names of queued files', () => {
    const file = new File(['abc'], 'contract.pdf', { type: 'application/pdf' });
    render(
      <FileUploadField
        files={[{ file, id: '1' }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText('contract.pdf')).toBeInTheDocument();
  });
});
