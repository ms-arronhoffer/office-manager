import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Icon from '@cloudscape-design/components/icon';

const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <ContentLayout header={<Header variant="h1">Page not found</Header>}>
      <Container>
        <Box textAlign="center" padding={{ vertical: 'xxl' }}>
          <SpaceBetween size="m">
            <Box variant="h2">
              <Icon name="status-warning" /> 404
            </Box>
            <Box>
              The page <code>{location.pathname}</code> does not exist or has been moved.
            </Box>
            <SpaceBetween direction="horizontal" size="xs" alignItems="center">
              <Button variant="primary" onClick={() => navigate('/')}>
                Go to Dashboard
              </Button>
              <Button onClick={() => navigate(-1)}>Go back</Button>
            </SpaceBetween>
          </SpaceBetween>
        </Box>
      </Container>
    </ContentLayout>
  );
};

export default NotFoundPage;
