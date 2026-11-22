/**
 * Phone uploads: stream the picked file from disk straight to the pre-signed R2 URL.
 *
 * Don't use fetch(uri).blob() here: on Android, fetch can't read the picker's file:// / content://
 * URIs - it answers with a "File not found" body, which then got uploaded instead of the video.
 * Web version: upload.web.ts.
 */

import { FileSystemUploadType, createUploadTask } from 'expo-file-system/legacy';

import { ApiError } from './api';

export async function uploadWithProgress(
  uri: string, url: string, headers: Record<string, string>, onProgress: (p: number) => void = () => {},
): Promise<void> {
  const task = createUploadTask(
    url,
    uri,
    { httpMethod: 'PUT', uploadType: FileSystemUploadType.BINARY_CONTENT, headers },
    ({ totalBytesSent, totalBytesExpectedToSend }) =>
      totalBytesExpectedToSend > 0 && onProgress(totalBytesSent / totalBytesExpectedToSend),
  );
  let res;
  try {
    res = await task.uploadAsync();
  } catch {
    throw new ApiError(0, 'Upload failed - check your connection and try again');
  }
  if (!res || res.status < 200 || res.status >= 300) {
    throw new ApiError(res?.status ?? 0, `Upload failed (${res?.status ?? 'no response'})`);
  }
  onProgress(1);
}

export const uploadToStorage = (uri: string, url: string, headers: Record<string, string>) =>
  uploadWithProgress(uri, url, headers);
