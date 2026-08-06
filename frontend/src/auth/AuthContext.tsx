import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { auth, organizations } from '@/api';
import { requestApiCachePurge } from '@/serviceWorkerRegistration';
import type { User, SignupRequest } from '@/types';

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithToken: (token?: string) => Promise<void>;
  googleLogin: (googleToken: string) => Promise<void>;
  signup: (data: SignupRequest) => Promise<void>;
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadUser = useCallback(async () => {
    try {
      const response = await auth.getMe();
      setUser(response.data);
      setToken('cookie');
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const login = async (email: string, password: string) => {
    await auth.login(email, password);
    setToken('cookie');
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const loginWithToken = async (_token?: string) => {
    setToken('cookie');
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const googleLogin = async (googleToken: string) => {
    await auth.googleAuth(googleToken);
    setToken('cookie');
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const signup = async (data: SignupRequest) => {
    await organizations.signup(data);
    setToken('cookie');
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const logout = async () => {
    await requestApiCachePurge();
    try {
      await auth.logout();
    } catch {
      // Local state is cleared even if the server session already expired.
    }
    setToken(null);
    setUser(null);
    window.location.href = '/login';
  };

  const refreshUser = async () => {
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!token && !!user,
        isLoading,
        login,
        loginWithToken,
        googleLogin,
        signup,
        refreshUser,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
