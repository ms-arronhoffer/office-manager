import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { legal } from '@/api';
import type { LegalDocument, LegalDocumentMeta } from '@/types';

const shellStyle: React.CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  flexDirection: 'column',
};

const bannerStyle: React.CSSProperties = {
  background: 'linear-gradient(135deg, #0972d3 0%, #033160 100%)',
  padding: '48px 24px',
  textAlign: 'center',
};

const LegalHeaderBanner: React.FC = () => (
  <div style={bannerStyle}>
    <Link to="/" style={{ textDecoration: 'none' }}>
      <div
        style={{
          fontSize: '2rem',
          fontWeight: 700,
          color: '#ffffff',
          letterSpacing: '-0.5px',
        }}
      >
        Portfolio Desk
      </div>
    </Link>
    <div style={{ fontSize: '1rem', color: 'rgba(255, 255, 255, 0.85)', marginTop: '8px' }}>
      Legal &amp; policies
    </div>
  </div>
);

const LegalList: React.FC = () => {
  const [docs, setDocs] = useState<LegalDocumentMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    legal
      .list()
      .then(({ data }) => {
        if (active) setDocs(data);
      })
      .catch(() => {
        if (active) setError('Unable to load legal documents. Please try again later.');
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <Container header={<Header variant="h2">Terms &amp; policies</Header>}>
      <SpaceBetween direction="vertical" size="l">
        {error && <Alert type="error">{error}</Alert>}
        {!docs && !error && <Spinner size="large" />}
        {docs && (
          <SpaceBetween direction="vertical" size="m">
            {docs.map((doc) => (
              <div key={doc.slug}>
                <Link to={`/legal/${doc.slug}`}>
                  <Box variant="h3">{doc.title}</Box>
                </Link>
                {doc.summary && (
                  <Box variant="p" color="text-body-secondary">
                    {doc.summary}
                  </Box>
                )}
                <Box variant="small" color="text-status-inactive">
                  Version {doc.version} · Effective {doc.effective_date}
                </Box>
              </div>
            ))}
          </SpaceBetween>
        )}
      </SpaceBetween>
    </Container>
  );
};

const LegalDocumentView: React.FC<{ slug: string }> = ({ slug }) => {
  const navigate = useNavigate();
  const [doc, setDoc] = useState<LegalDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setDoc(null);
    setError(null);
    legal
      .get(slug)
      .then(({ data }) => {
        if (active) setDoc(data);
      })
      .catch((err: unknown) => {
        if (!active) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
        setError(status === 404 ? 'This document could not be found.' : 'Unable to load this document.');
      });
    return () => {
      active = false;
    };
  }, [slug]);

  return (
    <Container
      header={
        <Header
          variant="h1"
          description={doc ? `Version ${doc.version} · Effective ${doc.effective_date}` : undefined}
          actions={
            <Button onClick={() => navigate('/legal')} iconName="arrow-left">
              All documents
            </Button>
          }
        >
          {doc ? doc.title : 'Legal document'}
        </Header>
      }
    >
      {error && <Alert type="error">{error}</Alert>}
      {!doc && !error && <Spinner size="large" />}
      {doc && (
        // The HTML is rendered on the server from trusted, first-party Markdown
        // shipped with the application (never from user input).
        <div className="legal-document" dangerouslySetInnerHTML={{ __html: doc.html }} />
      )}
    </Container>
  );
};

const LegalPage: React.FC = () => {
  const { slug } = useParams<{ slug?: string }>();

  return (
    <div style={shellStyle}>
      <LegalHeaderBanner />
      <Box padding={{ top: 'xxl', horizontal: 'xxl', bottom: 'xxxl' }}>
        <Box display="block">
          {slug ? <LegalDocumentView slug={slug} /> : <LegalList />}
        </Box>
      </Box>
    </div>
  );
};

export default LegalPage;
