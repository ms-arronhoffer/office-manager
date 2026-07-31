/**
 * Shared error messaging for the AI document-upload components.
 *
 * Large documents are accepted (the backend extracts and segments them), so the
 * server's own message is surfaced when it rejects an upload — e.g. a file over
 * the AI size ceiling, or a file type it cannot read — instead of the generic
 * "could not read the document" fallback.
 */
export function aiUploadErrorMessage(err: unknown): string {
  const response = (
    err as { response?: { status?: number; data?: { detail?: unknown } } }
  )?.response;
  const detail = typeof response?.data?.detail === 'string' ? response.data.detail : null;
  if (response?.status === 503) {
    return 'AI assist is not configured on the server. Add a Gemini API key to enable this.';
  }
  if (response?.status === 413) {
    return detail || 'That file is too large to process. Try splitting it into smaller documents.';
  }
  if (response?.status === 400 && detail) {
    return detail;
  }
  return 'Could not read the document. Please enter the details manually.';
}
