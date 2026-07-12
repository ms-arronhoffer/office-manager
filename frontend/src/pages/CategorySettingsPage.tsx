import React, { useCallback, useEffect, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Toggle from '@cloudscape-design/components/toggle';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import { useFlashbar } from '@/context/FlashbarContext';
import { organizations } from '@/api';
import type { CategoriesState, PrimaryCategory } from '@/types';

/**
 * Admin self-serve toggle UI for an org's primary business categories
 * (Commercial / Residential / Self Storage). Writes ``enabled_categories`` via
 * ``PUT /organizations/me/categories``; platform (super-admin) overrides always
 * win over the org's own list, so a category locked by a platform override is
 * shown as read-only.
 */
const CategorySettingsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [state, setState] = useState<CategoriesState | null>(null);
  const [enabled, setEnabled] = useState<Set<PrimaryCategory>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await organizations.getCategories();
      setState(res.data);
      setEnabled(new Set(res.data.enabled_categories));
    } catch {
      addFlash({ type: 'error', content: 'Failed to load category settings.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (category: PrimaryCategory, checked: boolean) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (checked) next.add(category);
      else next.delete(category);
      return next;
    });
  };

  const effectiveCount = state
    ? state.catalog.filter((c) => {
        const override = state.overrides[c];
        if (override !== undefined) return override;
        return enabled.has(c);
      }).length
    : 0;

  const save = async () => {
    if (!state) return;
    setSaving(true);
    try {
      const res = await organizations.updateCategories(
        state.catalog.filter((c) => enabled.has(c)),
      );
      setState(res.data);
      setEnabled(new Set(res.data.enabled_categories));
      addFlash({ type: 'success', content: 'Business categories updated.' });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({
        type: 'error',
        content: detail || 'Failed to update business categories.',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Container
      header={
        <Header
          variant="h1"
          description="Turn each line of business on or off. Disabling a category hides its surfaces and blocks new records; existing data is retained and is restored if the category is re-enabled. At least one category must stay enabled."
          actions={
            <Button variant="primary" loading={saving} disabled={loading || effectiveCount < 1} onClick={save}>
              Save changes
            </Button>
          }
        >
          Business categories
        </Header>
      }
    >
      {loading ? (
        <Box>Loading…</Box>
      ) : state ? (
        <SpaceBetween size="l">
          {effectiveCount < 1 && (
            <Alert type="warning">At least one category must remain enabled.</Alert>
          )}
          {state.catalog.map((category) => {
            const override = state.overrides[category];
            const platformLocked = override !== undefined;
            const checked = platformLocked ? Boolean(override) : enabled.has(category);
            const label = state.labels[category] || category;
            return (
              <Box key={category}>
                <SpaceBetween direction="horizontal" size="s">
                  <Toggle
                    checked={checked}
                    disabled={platformLocked}
                    onChange={(e) => toggle(category, e.detail.checked)}
                  >
                    {label}
                  </Toggle>
                  {platformLocked && (
                    <Badge color={override ? 'blue' : 'grey'}>
                      {override ? 'Enabled by platform' : 'Disabled by platform'}
                    </Badge>
                  )}
                </SpaceBetween>
              </Box>
            );
          })}
        </SpaceBetween>
      ) : (
        <Box>No category configuration available.</Box>
      )}
    </Container>
  );
};

export default CategorySettingsPage;
