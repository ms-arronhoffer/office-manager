import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Cards from '@cloudscape-design/components/cards';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Tabs from '@cloudscape-design/components/tabs';
import { emailTemplates } from '@/api';
import EmailBrandingWizard from '@/components/email/EmailBrandingWizard';
import EmailTemplateEditor from '@/components/email/EmailTemplateEditor';
import type { EmailBranding, EmailTemplateCatalogEntry } from '@/types';

/**
 * Email customization hub.
 *
 * The workflow is deliberately ordered rather than presented as a pile of
 * settings: brand the wrapper once, then adjust individual messages. Until
 * branding exists the messages tab says so, because editing wording before
 * setting a sender name and reply-to fixes the smaller problem first.
 */
const EmailCustomizationPage: React.FC = () => {
  const [entries, setEntries] = useState<EmailTemplateCatalogEntry[]>([]);
  const [branding, setBranding] = useState<EmailBranding | null>(null);
  const [selected, setSelected] = useState<EmailTemplateCatalogEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('branding');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [catalogRes, brandingRes] = await Promise.all([
        emailTemplates.catalog(),
        emailTemplates.getBranding(),
      ]);
      setEntries(catalogRes.data);
      setBranding(brandingRes.data);
      // Send an org that has already branded straight to the message list.
      setActiveTab(brandingRes.data.is_configured ? 'messages' : 'branding');
    } catch {
      setError('Could not load email settings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const customizedCount = useMemo(
    () => entries.filter((e) => e.is_customized).length,
    [entries],
  );

  const grouped = useMemo(() => {
    const byCategory = new Map<string, EmailTemplateCatalogEntry[]>();
    for (const entry of entries) {
      const list = byCategory.get(entry.category) ?? [];
      list.push(entry);
      byCategory.set(entry.category, list);
    }
    return Array.from(byCategory.entries());
  }, [entries]);

  const messagesTab = selected ? (
    <EmailTemplateEditor
      entry={selected}
      onClose={() => setSelected(null)}
      onChanged={load}
    />
  ) : (
    <SpaceBetween size="l">
      {branding && !branding.is_configured && (
        <Alert
          type="info"
          header="Set your branding first"
          action={<Button onClick={() => setActiveTab('branding')}>Set up branding</Button>}
        >
          Your sender name, reply-to address and logo apply to every message below.
          Setting them once is usually a bigger improvement than rewording any single email.
        </Alert>
      )}
      {grouped.map(([category, items]) => (
        <div key={category}>
          <Header variant="h3">{category}</Header>
          <Cards
            items={items}
            trackBy="key"
            cardsPerRow={[{ cards: 1 }, { minWidth: 720, cards: 2 }]}
            cardDefinition={{
              header: (item: EmailTemplateCatalogEntry) => (
                <SpaceBetween direction="horizontal" size="xs">
                  <span>{item.label}</span>
                  {item.is_customized ? (
                    <Badge color="blue">Customised</Badge>
                  ) : (
                    <Badge color="grey">Default</Badge>
                  )}
                </SpaceBetween>
              ),
              sections: [
                {
                  id: 'description',
                  content: (item: EmailTemplateCatalogEntry) => (
                    <Box variant="small" color="text-body-secondary">
                      {item.description}
                    </Box>
                  ),
                },
                {
                  id: 'action',
                  content: (item: EmailTemplateCatalogEntry) => (
                    <Button onClick={() => setSelected(item)}>
                      {item.is_customized ? 'Edit wording' : 'Customise'}
                    </Button>
                  ),
                },
              ],
            }}
            empty={<Box textAlign="center">No messages in this group.</Box>}
          />
        </div>
      ))}
    </SpaceBetween>
  );

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Control how emails sent on your behalf look, who they come from, and what they say."
          counter={customizedCount ? `(${customizedCount} customised)` : undefined}
          actions={<Button iconName="refresh" onClick={load} loading={loading} />}
        >
          Email customization
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && <Alert type="error">{error}</Alert>}
        <Tabs
          activeTabId={activeTab}
          onChange={({ detail }) => {
            setSelected(null);
            setActiveTab(detail.activeTabId);
          }}
          tabs={[
            {
              id: 'branding',
              label: 'Branding',
              content: <EmailBrandingWizard onSaved={setBranding} />,
            },
            {
              id: 'messages',
              label: `Messages${entries.length ? ` (${entries.length})` : ''}`,
              content: messagesTab,
            },
          ]}
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default EmailCustomizationPage;
