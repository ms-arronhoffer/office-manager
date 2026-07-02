import { useCallback, useEffect, useState } from 'react';

/**
 * PWA install affordance (Phase 1.6).
 *
 * Captures the browser's `beforeinstallprompt` event so the app can offer its
 * own "Install app" control instead of relying on the browser's default UI.
 * `canInstall` is false once installed or on browsers that don't fire the
 * event (e.g. iOS Safari), in which case no button is shown.
 */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export function useInstallPrompt(): { canInstall: boolean; promptInstall: () => void } {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);

  useEffect(() => {
    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => setDeferred(null);

    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const promptInstall = useCallback(() => {
    if (!deferred) return;
    void deferred.prompt();
    void deferred.userChoice.finally(() => setDeferred(null));
  }, [deferred]);

  return { canInstall: deferred !== null, promptInstall };
}
