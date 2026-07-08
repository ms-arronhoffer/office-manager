import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import React from 'react';
import HelpPage from '@/pages/HelpPage';

function renderHelp() {
  return render(
    <MemoryRouter initialEntries={['/help']}>
      <HelpPage />
    </MemoryRouter>,
  );
}

describe('HelpPage', () => {
  it('renders the guide header and topic sections', () => {
    renderHelp();
    expect(screen.getByRole('heading', { name: /Help & User Guide/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Getting started/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Finance & accounting/i })).toBeInTheDocument();
  });

  it('filters topics and articles by search term', async () => {
    const user = userEvent.setup();
    renderHelp();

    const search = screen.getByPlaceholderText(/Search help topics and tasks/i);
    await user.type(search, 'keyboard shortcuts');

    await waitFor(() => {
      expect(screen.getByText(/Ctrl \+ K focuses global search/i)).toBeInTheDocument();
    });
    // A clearly unrelated topic should be filtered out.
    expect(screen.queryByRole('heading', { name: /Commercial property management/i })).toBeNull();
  });

  it('shows an empty state when nothing matches', async () => {
    const user = userEvent.setup();
    renderHelp();

    const search = screen.getByPlaceholderText(/Search help topics and tasks/i);
    await user.type(search, 'zzznonexistentquery');

    await waitFor(() => {
      expect(screen.getByText(/No results/i)).toBeInTheDocument();
    });
  });
});
