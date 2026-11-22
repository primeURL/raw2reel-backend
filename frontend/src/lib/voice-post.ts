/** Web only (voice.web.ts): POST the note to /v1/transcribe. The phone uses Expo's native uploader. */

import { ApiError, currentToken } from './api';
import { API_URL } from './config';

export async function postVoiceNote(form: FormData): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/v1/transcribe`, { method: 'POST', headers: { Authorization: `Bearer ${currentToken()}` }, body: form });
  } catch (e) {
    throw new ApiError(0, `Couldn't send the voice note (${(e instanceof Error ? e.message : String(e)).slice(0, 120)})`);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, (data && typeof data.detail === 'string' && data.detail) || `Voice note failed (${res.status})`);
  return String(data.text ?? '');
}
