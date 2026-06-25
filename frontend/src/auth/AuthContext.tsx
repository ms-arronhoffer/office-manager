import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { auth, organizations } from '@/api';
import type { User, SignupRequest } from '@/types';

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  googleLogin: (googleToken: string) => Promise<void>;
  signup: (data: SignupRequest) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem('access_token'));
  const [isLoading, setIsLoading] = useState(true);

  const loadUser = useCallback(async () => {
    const storedToken = localStorage.getItem('access_token');
    if (!storedToken) {
      setIsLoading(false);
      return;
    }
    try {
      const response = await auth.getMe();
      setUser(response.data);
      setToken(storedToken);
    } catch {
      localStorage.removeItem('access_token');
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
    const response = await auth.login(email, password);
    const access_token = response.data.access_token!;
    localStorage.setItem('access_token', access_token);
    setToken(access_token);
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const loginWithToken = async (token: string) => {
    localStorage.setItem('access_token', token);
    setToken(token);
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const googleLogin = async (googleToken: string) => {
    const response = await auth.googleAuth(googleToken);
    const access_token = response.data.access_token!;
    localStorage.setItem('access_token', access_token);
    setToken(access_token);
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const signup = async (data: SignupRequest) => {
    const response = await organizations.signup(data);
    const { access_token } = response.data;
    localStorage.setItem('access_token', access_token);
    setToken(access_token);
    const userResponse = await auth.getMe();
    setUser(userResponse.data);
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    setToken(null);
    setUser(null);
    window.location.href = '/login';
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
