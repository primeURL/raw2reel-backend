/** Web: the recorder gives a blob: URL (webm/ogg); send it as a file. */

import { postVoiceNote } from './voice-post';

export async function transcribe(uri: string, language?: string | null): Promise<string> {
  const blob = await (await fetch(uri)).blob();
  const form = new FormData();
  const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm';
  form.append('audio', new File([blob], `note.${ext}`, { type: blob.type || 'audio/webm' }));
  if (language) form.append('language', language);
  return postVoiceNote(form);
}
