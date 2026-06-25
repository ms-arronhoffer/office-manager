import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const managersCreate = vi.fn();
const ticketCategoriesCreate = vi.fn();
const officesCreate = vi.fn();

vi.mock('@/api', () => ({
  managementCompanies: { create: vi.fn() },
  offices: { create: (...args: unknown[]) => officesCreate(...args) },
  managers: { create: (...args: unknown[]) => managersCreate(...args) },
  ticketCategories: { create: (...args: unknown[]) => ticketCategoriesCreate(...args) },
}));

const { ManagerQuickCreate, TicketCategoryQuickCreate, OfficeQuickCreate } = await import(
  '@/components/common/QuickCreateForms'
);
const { EntityQuickCreateSelect } = await import(
  '@/components/common/EntityQuickCreateSelect'
);

describe('QuickCreate modals', () => {
  beforeEach(() => {
    managersCreate.mockReset();
    ticketCategoriesCreate.mockReset();
    officesCreate.mockReset();
  });

  it('creates a manager and reports the new option', async () => {
    managersCreate.mockResolvedValue({ data: { id: 'm-1', name: 'Jane Doe' } });
    const onCreated = vi.fn();
    const onClose = vi.fn();

    render(
      <ManagerQuickCreate visible onClose={onClose} onCreated={onCreated} />,
    );

    const nameInput = screen.getByPlaceholderText('Manager name');
    fireEvent.change(nameInput, { target: { value: 'Jane Doe' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Manager' }));

    await waitFor(() => expect(managersCreate).toHaveBeenCalledTimes(1));
    expect(managersCreate).toHaveBeenCalledWith({ name: 'Jane Doe' });
    expect(onCreated).toHaveBeenCalledWith({ label: 'Jane Doe', value: 'm-1' });
    expect(onClose).toHaveBeenCalled();
  });

  it('disables submit until the required category name is provided', () => {
    render(
      <TicketCategoryQuickCreate visible onClose={vi.fn()} onCreated={vi.fn()} />,
    );
    const submit = screen.getByRole('button', { name: 'Create Category' });
    expect(submit).toBeDisabled();
  });
  it('disables office submit until required fields are valid', () => {
    render(<OfficeQuickCreate visible onClose={vi.fn()} onCreated={vi.fn()} />);
    const submit = screen.getByRole('button', { name: 'Create Office' });
    expect(submit).toBeDisabled();
    expect(officesCreate).not.toHaveBeenCalled();
  });
});

describe('EntityQuickCreateSelect', () => {
  it('renders the select trigger with an injected add-new option config', () => {
    const onChange = vi.fn();
    render(
      <EntityQuickCreateSelect
        selectedOption={null}
        onChange={onChange}
        options={[{ label: 'Existing', value: 'e-1' }]}
        placeholder="Select something"
        quickCreate={{
          label: '+ Add new thing…',
          render: ({ visible }) =>
            visible ? <div data-testid="modal-open">modal</div> : null,
        }}
      />,
    );

    // Trigger renders and the modal is not open until "+ Add new" is chosen.
    expect(screen.getByRole('button', { name: /Select something/ })).toBeInTheDocument();
    expect(screen.queryByTestId('modal-open')).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
