import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { preferences as preferencesApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import type { UserPreferences, PinnedOffice, SavedFilter } from '@/types';

const DEFAULT_PREFS: UserPreferences = {
  theme: 'light',
  density: 'comfortable',
  font_size: 'medium',
  page_sizes: {},
  visible_columns: {},
  default_filters: {},
  dashboard_widgets: {},
  navigation_open: true,
  pinned_offices: [],
  saved_filters: {},
};

interface PreferencesContextType {
  prefs: UserPreferences;
  getPageSize: (entity: string, fallback?: number) => number;
  setPageSize: (entity: string, size: number) => void;
  getVisibleColumns: (entity: string) => string[] | undefined;
  setVisibleColumns: (entity: string, cols: string[]) => void;
  getTheme: () => string;
  setTheme: (mode: string) => void;
  getDensity: () => 'comfortable' | 'compact';
  setDensity: (value: 'comfortable' | 'compact') => void;
  getFontSize: () => 'small' | 'medium' | 'large';
  setFontSize: (value: 'small' | 'medium' | 'large') => void;
  getDashboardWidgets: () => Record<string, boolean>;
  setDashboardWidget: (widgetId: string, visible: boolean) => void;
  getNavigationOpen: () => boolean;
  setNavigationOpen: (open: boolean) => void;
  getPinnedOffices: () => PinnedOffice[];
  togglePinnedOffice: (id: string, label: string) => void;
  getSavedFilters: (entity: string) => SavedFilter[];
  addSavedFilter: (entity: string, filter: SavedFilter) => void;
  removeSavedFilter: (entity: string, name: string) => void;
}

const PreferencesContext = createContext<PreferencesContextType | undefined>(undefined);

export const PreferencesProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const [prefs, setPrefs] = useState<UserPreferences>(DEFAULT_PREFS);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load preferences on auth
  useEffect(() => {
    if (!isAuthenticated) return;
    preferencesApi.get().then((res) => {
      setPrefs({ ...DEFAULT_PREFS, ...res.data });
    }).catch(() => {
      // non-critical, use defaults
    });
  }, [isAuthenticated]);

  // Debounced save
  const save = useCallback((updated: UserPreferences) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      preferencesApi.update(updated).catch(() => {});
    }, 500);
  }, []);

  const updatePrefs = useCallback((updater: (prev: UserPreferences) => UserPreferences) => {
    setPrefs((prev) => {
      const next = updater(prev);
      save(next);
      return next;
    });
  }, [save]);

  const getPageSize = useCallback((entity: string, fallback = 20) => {
    return prefs.page_sizes[entity] ?? fallback;
  }, [prefs]);

  const setPageSize = useCallback((entity: string, size: number) => {
    updatePrefs((p) => ({
      ...p,
      page_sizes: { ...p.page_sizes, [entity]: size },
    }));
  }, [updatePrefs]);

  const getVisibleColumns = useCallback((entity: string) => {
    return prefs.visible_columns[entity];
  }, [prefs]);

  const setVisibleColumns = useCallback((entity: string, cols: string[]) => {
    updatePrefs((p) => ({
      ...p,
      visible_columns: { ...p.visible_columns, [entity]: cols },
    }));
  }, [updatePrefs]);

  const getTheme = useCallback(() => prefs.theme, [prefs]);

  const setTheme = useCallback((mode: string) => {
    updatePrefs((p) => ({ ...p, theme: mode }));
  }, [updatePrefs]);

  const getDensity = useCallback(() => prefs.density ?? 'comfortable', [prefs]);

  const setDensity = useCallback((value: 'comfortable' | 'compact') => {
    updatePrefs((p) => ({ ...p, density: value }));
  }, [updatePrefs]);

  const getFontSize = useCallback(() => prefs.font_size ?? 'medium', [prefs]);

  const setFontSize = useCallback((value: 'small' | 'medium' | 'large') => {
    updatePrefs((p) => ({ ...p, font_size: value }));
  }, [updatePrefs]);

  const getDashboardWidgets = useCallback(() => prefs.dashboard_widgets ?? {}, [prefs]);

  const setDashboardWidget = useCallback((widgetId: string, visible: boolean) => {
    updatePrefs((p) => ({
      ...p,
      dashboard_widgets: { ...p.dashboard_widgets, [widgetId]: visible },
    }));
  }, [updatePrefs]);

  const getNavigationOpen = useCallback(() => prefs.navigation_open ?? true, [prefs]);

  const setNavigationOpen = useCallback((open: boolean) => {
    updatePrefs((p) => ({ ...p, navigation_open: open }));
  }, [updatePrefs]);

  const getPinnedOffices = useCallback(() => prefs.pinned_offices ?? [], [prefs]);

  const togglePinnedOffice = useCallback((id: string, label: string) => {
    updatePrefs((p) => {
      const current = p.pinned_offices ?? [];
      const exists = current.some((o) => o.id === id);
      return {
        ...p,
        pinned_offices: exists
          ? current.filter((o) => o.id !== id)
          : [...current, { id, label }],
      };
    });
  }, [updatePrefs]);

  const getSavedFilters = useCallback((entity: string) => {
    return (prefs.saved_filters ?? {})[entity] ?? [];
  }, [prefs]);

  const addSavedFilter = useCallback((entity: string, filter: SavedFilter) => {
    updatePrefs((p) => {
      const current = (p.saved_filters ?? {})[entity] ?? [];
      return {
        ...p,
        saved_filters: {
          ...p.saved_filters,
          [entity]: [...current.filter((f) => f.name !== filter.name), filter],
        },
      };
    });
  }, [updatePrefs]);

  const removeSavedFilter = useCallback((entity: string, name: string) => {
    updatePrefs((p) => {
      const current = (p.saved_filters ?? {})[entity] ?? [];
      return {
        ...p,
        saved_filters: {
          ...p.saved_filters,
          [entity]: current.filter((f) => f.name !== name),
        },
      };
    });
  }, [updatePrefs]);

  return (
    <PreferencesContext.Provider
      value={{
        prefs,
        getPageSize, setPageSize,
        getVisibleColumns, setVisibleColumns,
        getTheme, setTheme,
        getDensity, setDensity,
        getFontSize, setFontSize,
        getDashboardWidgets, setDashboardWidget,
        getNavigationOpen, setNavigationOpen,
        getPinnedOffices, togglePinnedOffice,
        getSavedFilters, addSavedFilter, removeSavedFilter,
      }}
    >
      {children}
    </PreferencesContext.Provider>
  );
};

export const usePreferences = (): PreferencesContextType => {
  const context = useContext(PreferencesContext);
  if (!context) {
    throw new Error('usePreferences must be used within a PreferencesProvider');
  }
  return context;
};
