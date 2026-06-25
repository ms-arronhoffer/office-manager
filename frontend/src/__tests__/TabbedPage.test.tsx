import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import React from 'react';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="pathname">{location.pathname}</div>;
}

const tabs: TabbedPageTab[] = [
  { id: 'one', label: 'One', href: '/hub', content: <div>Panel One</div> },
  { id: 'two', label: 'Two', href: '/hub/two', content: <div>Panel Two</div> },
];

function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LocationProbe />
      <Routes>
        <Route path="/hub" element={<TabbedPage tabs={tabs} />} />
        <Route path="/hub/two" element={<TabbedPage tabs={tabs} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('TabbedPage', () => {
  it('selects the active tab from the URL', () => {
    renderAt('/hub/two');
    expect(screen.getByText('Panel Two')).toBeInTheDocument();
  });

  it('defaults to the first tab on the base path', () => {
    renderAt('/hub');
    expect(screen.getByText('Panel One')).toBeInTheDocument();
  });

  it('navigates to the tab href when a tab is selected', async () => {
    const user = userEvent.setup();
    renderAt('/hub');
    await user.click(screen.getByRole('tab', { name: 'Two' }));
    await waitFor(() => {
      expect(screen.getByTestId('pathname').textContent).toBe('/hub/two');
    });
  });

  it('renders nothing when there are no tabs', () => {
    const { container } = render(
      <MemoryRouter>
        <TabbedPage tabs={[]} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[role="tab"]')).toBeNull();
  });
});
