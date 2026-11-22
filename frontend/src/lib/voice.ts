/**
 * Phone: send the recorded voice note to the server's Whisper (free) and get the text back.
 *
 * Uses Expo's native uploader (multipart), not fetch + FormData: this SDK's fetch can't read local
 * file:// recordings - the request failed on the phone before it was ever sent. Web: voice.web.ts.
 */

import { FileSystemUploadType, uploadAsync } from 'expo-file-system/legacy';

import { ApiError, currentToken } from './api';
import { API_URL } from './config';

export async function transcribe(uri: string, language?: string | null): Promise<string> {
  let res;
  try {
    res = await uploadAsync(`${API_URL}/v1/transcribe`, uri, {
      httpMethod: 'POST',
      uploadType: FileSystemUploadType.MULTIPART,
      fieldName: 'audio',
      mimeType: 'audio/m4a',
      parameters: language ? { language } : {},
      headers: { Authorization: `Bearer ${currentToken()}` },
    });
  } catch (e) {
    const why = e instanceof Error ? e.message : String(e);
    throw new ApiError(0, `Couldn't send the voice note (${why.slice(0, 120)})`);
  }
  let data: { text?: string; detail?: unknown } | null = null;
  try {
    data = JSON.parse(res.body);
  } catch {
    // non-JSON error page
  }
  if (res.status < 200 || res.status >= 300) {
    throw new ApiError(res.status, (data && typeof data.detail === 'string' && data.detail) || `Voice note failed (${res.status})`);
  }
  return String(data?.text ?? '');
}
