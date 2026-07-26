import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import Spinner from '@cloudscape-design/components/spinner';
import Box from '@cloudscape-design/components/box';
import { useAuth } from './AuthContext';
import LegalGate from '@/components/common/LegalGate';

interface ProtectedRouteProps {
  children: React.ReactNode;
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
  const { isAuthenticated, isLoading, user } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Gate the app until the user has accepted the required legal documents. The
  // org creator accepts at signup; every other user must accept on first login
  // before their account becomes active.
  if (user?.legal_acceptance_required) {
    return <LegalGate />;
  }

  return <>{children}</>;
};

export default ProtectedRoute;
