import React from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Icon from '@cloudscape-design/components/icon';
import { useAuth } from './AuthContext';

interface SuperAdminGuardProps {
  children: React.ReactNode;
}

/** Restricts a route to platform super-admins (is_super_admin === true). */
const SuperAdminGuard: React.FC<SuperAdminGuardProps> = ({ children }) => {
  const { user } = useAuth();
  const navigate = useNavigate();

  // Unauthenticated users go to login; signed-in non-super-admins get a clear
  // access-denied screen rather than a silent redirect.
  if (!user) {
    return <Navigate to="/" replace />;
  }

  if (!user.is_super_admin) {
    return (
      <ContentLayout header={<Header variant="h1">Access denied</Header>}>
        <Container>
          <Box textAlign="center" padding={{ vertical: 'xxl' }}>
            <SpaceBetween size="m">
              <Box variant="h2">
                <Icon name="status-warning" /> 403
              </Box>
              <Box>This page is restricted to platform super-admins.</Box>
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
  }

  return <>{children}</>;
};

export default SuperAdminGuard;
