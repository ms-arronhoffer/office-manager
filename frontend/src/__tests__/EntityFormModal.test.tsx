import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

const { default: EntityFormModal } = await import(
  '@/components/common/EntityFormModal'
);

describe('EntityFormModal', () => {
  it('renders the title, children, and default footer labels', () => {
    render(
      <EntityFormModal
        visible
        title="Add resident"
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      >
        <div>form body</div>
      </EntityFormModal>,
    );

    expect(screen.getByText('Add resident')).toBeInTheDocument();
    expect(screen.getByText('form body')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('surfaces an inline error alert', () => {
    render(
      <EntityFormModal
        visible
        title="Add resident"
        error="Something went wrong"
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      >
        <div>body</div>
      </EntityFormModal>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('invokes onSubmit and onCancel from the footer buttons', () => {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(
      <EntityFormModal
        visible
        title="Add resident"
        submitLabel="Create"
        onSubmit={onSubmit}
        onCancel={onCancel}
      >
        <div>body</div>
      </EntityFormModal>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('disables the submit button when submitDisabled is set', () => {
    render(
      <EntityFormModal
        visible
        title="Add resident"
        submitDisabled
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      >
        <div>body</div>
      </EntityFormModal>,
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});
