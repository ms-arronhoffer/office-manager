/**
 * Copy text to the clipboard with a graceful fallback.
 *
 * `navigator.clipboard` is only available in secure contexts (HTTPS or
 * localhost). When the app is served over plain HTTP — or when the async
 * Clipboard API rejects (permissions, focus, etc.) — the modern call silently
 * fails, which is what made the portal "Copy" button appear broken. This helper
 * tries the async API first and falls back to a hidden `<textarea>` +
 * `document.execCommand('copy')` so copying works everywhere.
 *
 * @returns `true` when the text was copied, `false` otherwise.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  // Preferred path: async Clipboard API (secure contexts only).
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the legacy approach below.
    }
  }

  // Legacy fallback: works in non-secure contexts and older browsers.
  if (typeof document === 'undefined') return false;
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    // Keep it out of view and unfocusable to avoid scroll jumps.
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-9999px';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}
