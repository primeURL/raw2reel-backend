/** Web uploads: the picker gives a blob: URL; PUT it to the pre-signed R2 URL with XHR for progress. */

import { ApiError } from './api';

async function readBlob(uri: string): Promise<Blob> {
  const res = await fetch(uri);
  if (!res.ok) throw new ApiError(res.status, "Couldn't read that video file");
  const blob = await res.blob();
  if (blob.size < 1024) throw new ApiError(0, "That file is empty or isn't a video");
  return blob;
}

export async function uploadWithProgress(
  uri: string, url: string, headers: Record<string, string>, onProgress: (p: number) => void = () => {},
): Promise<void> {
  const file = await readBlob(uri);
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new ApiError(xhr.status, `Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new ApiError(0, 'Upload failed - check your connection and try again'));
    xhr.send(file);
  });
  onProgress(1);
}

export const uploadToStorage = (uri: string, url: string, headers: Record<string, string>) =>
  uploadWithProgress(uri, url, headers);
