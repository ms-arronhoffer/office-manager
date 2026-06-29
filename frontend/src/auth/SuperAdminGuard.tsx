import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';

interface SuperAdminGuardProps {
  children: React.ReactNode;
}

/** Restricts a route to platform super-admins (is_super_admin === true). */
const SuperAdminGuard: React.FC<SuperAdminGuardProps> = ({ children }) => {
  const { user } = useAuth();

  if (!user || !user.is_super_admin) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};

export default SuperAdminGuard;
