/** Save a rendered reel to the phone's gallery, or open the share sheet (Instagram, WhatsApp...).
 * Both download the signed video URL to the app cache first. Web version: share.web.ts. */

import Constants, { ExecutionEnvironment } from 'expo-constants';
import { Directory, File, Paths } from 'expo-file-system';
import { Asset, requestPermissionsAsync } from 'expo-media-library';
import * as Sharing from 'expo-sharing';

async function download(url: string, name: string): Promise<string> {
  const dir = new Directory(Paths.cache, 'renders');
  if (!dir.exists) dir.create();
  const target = new File(dir, name);
  if (target.exists) target.delete();
  const file = await File.downloadFileAsync(url, target);
  return file.uri;
}

/** Expo Go (the test app) may not save to the gallery on Android - it lacks the permission.
 * A real build of Raw2Reel can; until then Save opens the share sheet instead. */
const inExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

export async function saveToGallery(url: string, name: string): Promise<string | null> {
  let perm;
  try {
    perm = await requestPermissionsAsync(true, ['video']); // add-only access is enough to save
  } catch (e) {
    if (!inExpoGo) throw e;
    await shareVideo(url, name);
    return 'Expo Go can’t save to the gallery directly. Pick Photos or Files in the share sheet to save it.';
  }
  if (!perm.granted) throw new Error('Allow Raw2Reel to add videos to your gallery to save it.');
  await Asset.create(await download(url, name));
  return 'Saved to your gallery';
}

export async function shareVideo(url: string, name: string): Promise<string | null> {
  if (!(await Sharing.isAvailableAsync())) throw new Error("Sharing isn't available on this device.");
  await Sharing.shareAsync(await download(url, name), { mimeType: 'video/mp4', UTI: 'public.mpeg-4', dialogTitle: 'Share your reel' });
  return null;
}
