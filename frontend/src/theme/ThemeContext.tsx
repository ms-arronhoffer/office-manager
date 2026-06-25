import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { applyMode, Mode } from '@cloudscape-design/global-styles';
import { usePreferences } from '@/context/PreferencesContext';
import './density-fallback.css';
import './font-scale.css';

type DensityValue = 'comfortable' | 'compact';
type FontSizeValue = 'small' | 'medium' | 'large';

const FONT_SCALE_MAP: Record<FontSizeValue, number> = {
  small: 0.875,
  medium: 1,
  large: 1.125,
};

interface ThemeContextType {
  mode: 'light' | 'dark';
  toggleMode: () => void;
  density: DensityValue;
  setDensity: (value: DensityValue) => void;
  fontSize: FontSizeValue;
  setFontSize: (value: FontSizeValue) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// Resolve applyDensity once — may not exist in older Cloudscape versions
type ApplyDensityFn = (d: DensityValue) => void;
const applyDensityRef: { current: ApplyDensityFn | null; resolved: boolean } = {
  current: null,
  resolved: false,
};

function resolveApplyDensity(): Promise<void> {
  if (applyDensityRef.resolved) return Promise.resolve();
  return import('@cloudscape-design/global-styles')
    .then((gs) => {
      if ('applyDensity' in gs && 'Density' in gs) {
        const gsMod = gs as typeof gs & { applyDensity: (d: unknown) => void; Density: { Compact: unknown; Comfortable: unknown } };
        applyDensityRef.current = (d: DensityValue) => {
          gsMod.applyDensity(d === 'compact' ? gsMod.Density.Compact : gsMod.Density.Comfortable);
        };
      }
    })
    .catch(() => {})
    .finally(() => {
      applyDensityRef.resolved = true;
    });
}

function applyDensityValue(d: DensityValue) {
  if (applyDensityRef.current) {
    applyDensityRef.current(d);
  } else {
    document.body.classList.toggle('awsui-compact-mode', d === 'compact');
  }
}

function applyFontScale(size: FontSizeValue) {
  document.documentElement.style.setProperty('--app-font-scale', String(FONT_SCALE_MAP[size] ?? 1));
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const {
    getTheme, setTheme: saveTheme,
    getDensity: getPrefDensity, setDensity: saveDensity,
    getFontSize: getPrefFontSize, setFontSize: saveFontSize,
  } = usePreferences();

  const [mode, setMode] = useState<'light' | 'dark'>(() => {
    const stored = getTheme();
    return stored === 'dark' ? 'dark' : 'light';
  });

  const [density, setDensityState] = useState<DensityValue>(() => {
    const stored = getPrefDensity();
    return stored === 'compact' ? 'compact' : 'comfortable';
  });

  const [fontSize, setFontSizeState] = useState<FontSizeValue>(() => {
    const stored = getPrefFontSize();
    return (['small', 'medium', 'large'] as FontSizeValue[]).includes(stored) ? stored : 'medium';
  });

  const densityResolvedRef = useRef(false);

  // Apply theme mode
  useEffect(() => {
    applyMode(mode === 'dark' ? Mode.Dark : Mode.Light);
  }, [mode]);

  // Sync mode from server preferences
  useEffect(() => {
    const serverTheme = getTheme();
    if (serverTheme === 'dark' || serverTheme === 'light') {
      setMode(serverTheme);
    }
  }, [getTheme]);

  // Resolve and apply density
  useEffect(() => {
    if (!densityResolvedRef.current) {
      resolveApplyDensity().then(() => {
        densityResolvedRef.current = true;
        applyDensityValue(density);
      });
    } else {
      applyDensityValue(density);
    }
  }, [density]);

  // Sync density from server preferences
  useEffect(() => {
    const serverDensity = getPrefDensity();
    if (serverDensity === 'compact' || serverDensity === 'comfortable') {
      setDensityState(serverDensity);
    }
  }, [getPrefDensity]);

  // Apply font scale
  useEffect(() => {
    applyFontScale(fontSize);
  }, [fontSize]);

  // Sync font size from server preferences
  useEffect(() => {
    const serverSize = getPrefFontSize();
    if ((['small', 'medium', 'large'] as FontSizeValue[]).includes(serverSize)) {
      setFontSizeState(serverSize);
    }
  }, [getPrefFontSize]);

  const toggleMode = useCallback(() => {
    setMode((prev) => {
      const next = prev === 'light' ? 'dark' : 'light';
      saveTheme(next);
      return next;
    });
  }, [saveTheme]);

  const setDensity = useCallback((value: DensityValue) => {
    setDensityState(value);
    saveDensity(value);
  }, [saveDensity]);

  const setFontSize = useCallback((value: FontSizeValue) => {
    setFontSizeState(value);
    saveFontSize(value);
  }, [saveFontSize]);

  return (
    <ThemeContext.Provider value={{ mode, toggleMode, density, setDensity, fontSize, setFontSize }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = (): ThemeContextType => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
