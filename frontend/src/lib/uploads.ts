/**
 * Clip uploads that live outside any one screen: pick on "New reel", keep uploading while the
 * user moves to the reel screen. Each reel screen reads its own uploads with useUploads(projectId).
 */

import * as ImagePicker from 'expo-image-picker';
import { useMemo, useSyncExternalStore } from 'react';

import { api } from './api';
import { uploadWithProgress } from './upload';

export const MAX_CLIPS = 12;
export const MAX_CLIP_SECONDS = 300;
const PARALLEL_UPLOADS = 3;

export interface LocalUpload {
  key: string;
  projectId: string;
  name: string;
  progress: number;
  error?: string;
}

export type PickedClip = ImagePicker.ImagePickerAsset;

let items: LocalUpload[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const set = (next: LocalUpload[]) => {
  items = next;
  emit();
};
const patch = (key: string, p: Partial<LocalUpload>) => set(items.map((x) => (x.key === key ? { ...x, ...p } : x)));

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useUploads(projectId: string) {
  const all = useSyncExternalStore(subscribe, () => items, () => items);
  return useMemo(() => all.filter((u) => u.projectId === projectId), [all, projectId]);
}

export const dismissUpload = (key: string) => set(items.filter((x) => x.key !== key));

/** Open the gallery. Returns the picked videos (in the order picked) and a note about skipped ones. */
export async function pickClips(room: number): Promise<{ clips: PickedClip[]; note: string | null }> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) return { clips: [], note: 'Allow access to your videos to add clips.' };
  const res = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ['videos'], allowsEditing: false, allowsMultipleSelection: true, selectionLimit: room, orderedSelection: true,
  });
  if (res.canceled || !res.assets?.length) return { clips: [], note: null };
  const picked = res.assets.slice(0, room);
  const tooLong = picked.filter((a) => a.duration && a.duration / 1000 > MAX_CLIP_SECONDS);
  return {
    clips: picked.filter((a) => !tooLong.includes(a)),
    note: tooLong.length ? `${tooLong.length} clip${tooLong.length === 1 ? '' : 's'} longer than 5 minutes ${tooLong.length === 1 ? 'was' : 'were'} skipped.` : null,
  };
}

/** Upload picked clips to a reel. refresh() is called whenever the server's clip list changes. */
export async function uploadClips(projectId: string, clips: PickedClip[], refresh: () => void) {
  const mine = clips.map((a, i) => ({
    a, item: { key: `${Date.now()}-${i}-${Math.random().toString(36).slice(2, 6)}`, projectId, name: a.fileName ?? `clip ${i + 1}`, progress: 0 },
  }));
  set([...items, ...mine.map((m) => m.item)]);

  // 1. book every clip's slot first, one by one: positions C1, C2... follow the order picked
  const jobs: { key: string; uri: string; ticket: Awaited<ReturnType<typeof api.clipUploadUrl>> }[] = [];
  for (const { a, item } of mine) {
    try {
      const ticket = await api.clipUploadUrl(projectId, a.fileName ?? 'clip.mp4', a.mimeType ?? 'video/mp4', a.fileSize ?? undefined);
      jobs.push({ key: item.key, uri: a.uri, ticket });
    } catch (e) {
      patch(item.key, { error: e instanceof Error ? e.message : 'Upload failed' });
    }
  }
  refresh();

  // 2. upload 3 at a time - faster than one by one without starving a phone connection
  let next = 0;
  const worker = async () => {
    while (next < jobs.length) {
      const { key, uri, ticket } = jobs[next++];
      try {
        await uploadWithProgress(uri, ticket.upload_url, ticket.headers, (progress) => patch(key, { progress }));
        await api.completeClip(projectId, ticket.clip_id);
        dismissUpload(key);
      } catch (e) {
        patch(key, { error: e instanceof Error ? e.message : 'Upload failed' });
      }
      refresh();
    }
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL_UPLOADS, jobs.length) }, worker));
}
