import React, { useCallback, useEffect, useRef, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import { maintenance as maintenanceApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type { MaintenanceCatalogCategory } from '@/types';

type EditableTopic = {
  key: string;
  value?: string;
  label: string;
};

const toEditableTopics = (category: MaintenanceCatalogCategory): EditableTopic[] =>
  category.subtopics.map((subtopic) => ({
    key: subtopic.value,
    value: subtopic.value,
    label: subtopic.label,
  }));

const MaintenanceTopicsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [categories, setCategories] = useState<MaintenanceCatalogCategory[]>([]);
  const [drafts, setDrafts] = useState<Record<string, EditableTopic[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingCategory, setSavingCategory] = useState<string | null>(null);
  const [resettingCategory, setResettingCategory] = useState<string | null>(null);
  const nextTopicId = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await maintenanceApi.catalog();
      const nextCategories = res.data.categories ?? [];
      setCategories(nextCategories);
      setDrafts(
        nextCategories.reduce<Record<string, EditableTopic[]>>((acc, category) => {
          acc[category.value] = toEditableTopics(category);
          return acc;
        }, {}),
      );
    } catch {
      setError('Failed to load maintenance topics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const updateDraft = (category: string, updater: (current: EditableTopic[]) => EditableTopic[]) => {
    setDrafts((current) => ({ ...current, [category]: updater(current[category] ?? []) }));
  };

  const saveCategory = async (category: string) => {
    setSavingCategory(category);
    try {
      const res = await maintenanceApi.updateCategorySubtopics(category, {
        subtopics: (drafts[category] ?? []).map((topic) => ({
          value: topic.value || undefined,
          label: topic.label,
        })),
      });
      setCategories((current) => current.map((item) => (item.value === category ? res.data : item)));
      setDrafts((current) => ({ ...current, [category]: toEditableTopics(res.data) }));
      addFlash({ type: 'success', content: 'Maintenance topics updated.' });
    } catch {
      addFlash({ type: 'error', content: 'Failed to update maintenance topics.' });
    } finally {
      setSavingCategory(null);
    }
  };

  const resetCategory = async (category: string) => {
    setResettingCategory(category);
    try {
      const res = await maintenanceApi.resetCategorySubtopics(category);
      setCategories((current) => current.map((item) => (item.value === category ? res.data : item)));
      setDrafts((current) => ({ ...current, [category]: toEditableTopics(res.data) }));
      addFlash({ type: 'success', content: 'Maintenance topics reset to defaults.' });
    } catch {
      addFlash({ type: 'error', content: 'Failed to reset maintenance topics.' });
    } finally {
      setResettingCategory(null);
    }
  };

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Configure the topic choices shown for assets and tasks in each maintenance category."
          actions={<Button iconName="refresh" onClick={load}>Refresh</Button>}
        >
          Maintenance Topics
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        {loading ? (
          <Box padding="l" textAlign="center"><Spinner size="large" /></Box>
        ) : (
          categories.map((category) => (
            <Container
              key={category.value}
              header={
                <Header
                  variant="h2"
                  description="Add, rename, remove, or reset topics for this category."
                  actions={
                    <SpaceBetween direction="horizontal" size="xs">
                      <Button
                        onClick={() => resetCategory(category.value)}
                        loading={resettingCategory === category.value}
                      >
                        Reset defaults
                      </Button>
                      <Button
                        variant="primary"
                        onClick={() => saveCategory(category.value)}
                        loading={savingCategory === category.value}
                      >
                        Save topics
                      </Button>
                    </SpaceBetween>
                  }
                >
                  {category.label}
                </Header>
              }
            >
              <SpaceBetween size="m">
                {(drafts[category.value] ?? []).map((topic, index) => (
                  <SpaceBetween key={topic.key} direction="horizontal" size="s">
                    <div style={{ flex: 1 }}>
                      <FormField label={`Topic ${index + 1}`} stretch>
                        <Input
                          value={topic.label}
                          onChange={({ detail }) => {
                            updateDraft(category.value, (current) =>
                              current.map((item) => (
                                item.key === topic.key ? { ...item, label: detail.value } : item
                              )));
                          }}
                          placeholder="Topic label"
                        />
                      </FormField>
                    </div>
                    <Button
                      iconName="remove"
                      onClick={() => {
                        updateDraft(category.value, (current) =>
                          current.filter((item) => item.key !== topic.key));
                      }}
                    >
                      Remove
                    </Button>
                  </SpaceBetween>
                ))}
                <Button
                  onClick={() => {
                    nextTopicId.current += 1;
                    updateDraft(category.value, (current) => [
                      ...current,
                      { key: `new-${category.value}-${nextTopicId.current}`, label: '' },
                    ]);
                  }}
                >
                  Add topic
                </Button>
              </SpaceBetween>
            </Container>
          ))
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default MaintenanceTopicsPage;
