import React, { createContext, useContext, useState, useEffect } from 'react';
import { siteSettings as siteSettingsApi } from '@/api';
import type { SiteSettings } from '@/api';

const DEFAULTS: SiteSettings = {
  company_name: 'Portfolio Desk',
  company_address: '',
  company_phone: '',
  company_email: '',
  login_subtitle: 'Sign in to manage your offices, leases, and facilities',
  login_form_header: 'Sign In',
  login_form_description: 'Enter your credentials to access the application',
  sla_high_days: 1,
  sla_medium_days: 3,
  sla_low_days: 7,
};

interface SiteSettingsContextType {
  settings: SiteSettings;
  reload: () => void;
}

const SiteSettingsContext = createContext<SiteSettingsContextType>({
  settings: DEFAULTS,
  reload: () => {},
});

export const SiteSettingsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [settings, setSettings] = useState<SiteSettings>(DEFAULTS);

  const load = () => {
    siteSettingsApi.get().then((res) => {
      setSettings({ ...DEFAULTS, ...res.data });
    }).catch(() => {
      // Non-critical — fall back to defaults
    });
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <SiteSettingsContext.Provider value={{ settings, reload: load }}>
      {children}
    </SiteSettingsContext.Provider>
  );
};

export const useSiteSettings = (): SiteSettingsContextType => useContext(SiteSettingsContext);
