/**
 * Loader for Plaid Link, the hosted widget that collects a user's bank
 * credentials and returns a short-lived `public_token`.
 *
 * Plaid requires credentials to be entered inside their own iframe, so the
 * script is loaded from Plaid's CDN on demand rather than bundled. Nothing here
 * ever sees a username, password or account number.
 */

const PLAID_LINK_SRC = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js';

interface PlaidHandler {
  open: () => void;
  exit: () => void;
  destroy: () => void;
}

interface PlaidLinkMetadata {
  institution?: { name?: string; institution_id?: string } | null;
  accounts?: { id: string; name?: string; mask?: string }[];
}

interface PlaidCreateOptions {
  token: string;
  onSuccess: (publicToken: string, metadata: PlaidLinkMetadata) => void;
  onExit?: (err: unknown) => void;
}

declare global {
  interface Window {
    Plaid?: { create: (options: PlaidCreateOptions) => PlaidHandler };
  }
}

let loader: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.Plaid) return Promise.resolve();
  if (loader) return loader;
  loader = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = PLAID_LINK_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      loader = null;
      reject(new Error('Could not load Plaid Link. Check your network connection.'));
    };
    document.head.appendChild(script);
  });
  return loader;
}

/**
 * Open Plaid Link and resolve with the resulting public token, or `null` when
 * the user closes the widget without finishing.
 */
export async function openPlaidLink(
  linkToken: string,
): Promise<{ publicToken: string; metadata: PlaidLinkMetadata } | null> {
  await loadScript();
  if (!window.Plaid) throw new Error('Plaid Link is unavailable.');

  return new Promise((resolve, reject) => {
    const handler = window.Plaid!.create({
      token: linkToken,
      onSuccess: (publicToken, metadata) => {
        handler.destroy();
        resolve({ publicToken, metadata });
      },
      onExit: (err) => {
        handler.destroy();
        if (err) reject(err instanceof Error ? err : new Error('Bank connection was cancelled.'));
        else resolve(null);
      },
    });
    handler.open();
  });
}

export default openPlaidLink;
