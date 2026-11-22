/**
 * One reel: add clips (uploaded straight to storage with progress) -> they are checked and analysed
 * -> generate the edit plan (1 AI call, confirmed first) -> review, edit and render it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { ConfirmAI } from '@/components/confirm-ai';
import { Button, Card, Loading, Message, ProgressBar, Screen, SectionTitle, StatusChip, formatSeconds } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { uploadWithProgress } from '@/lib/upload';
import type { Clip, Project } from '@/lib/types';

const MAX_CLIPS = 12;
const MAX_CLIP_SECONDS = 300;
const PARALLEL_UPLOADS = 3;
const BUSY = new Set(['pending', 'downloading', 'processing']);
const clipBusy = (c: Clip) => BUSY.has(c.status) || (c.status === 'ready' && (!c.analysis_status || BUSY.has(c.analysis_status)));

interface LocalUpload {
  key: string;
  name: string;
  progress: number;
  error?: string;
}

export default function ReelScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [uploads, setUploads] = useState<LocalUpload[]>([]);
  const q = useQuery({
    queryKey: ['project', id],
    queryFn: () => api.project(id),
    refetchInterval: (query) => {
      const p = query.state.data;
      return p && (p.status === 'analyzing' || p.status === 'rendering' || p.clips.some(clipBusy)) ? 3000 : false;
    },
  });

  if (q.isPending) return <Loading />;
  if (q.isError) return <Message title="Couldn't load this reel" body={q.error.message} />;
  const p = q.data;

  return (
    <>
      <Stack.Screen options={{ title: p.title }} />
      <Screen title={p.title} right={<StatusChip status={p.status} />} onRefresh={q.refetch}>
        <Latest projectId={p.id} />
        <Brief p={p} />
        <Clips p={p} uploads={uploads} setUploads={setUploads} />
        <Plan p={p} uploading={uploads.some((u) => !u.error)} />
        <DeleteReel id={p.id} />
      </Screen>
    </>
  );
}

// latest video ----------------------------------------------------------------------

function Latest({ projectId }: { projectId: string }) {
  const t = useTheme();
  const renders = useQuery({
    queryKey: ['renders', projectId],
    queryFn: () => api.renders(projectId),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'pending' || r.status === 'processing') ? 1500 : false),
  });
  const latest = renders.data?.find((r) => r.status === 'ready');
  const working = renders.data?.find((r) => r.status === 'pending' || r.status === 'processing');
  if (!latest && !working) return null;
  return (
    <Card style={styles.clipRow} onPress={latest ? () => router.push({ pathname: '/reel/watch/[renderId]', params: { renderId: latest.id, projectId } }) : undefined}>
      <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]}>
        {latest?.thumbnail_url ? <Image source={{ uri: latest.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        {latest ? (
          <>
            <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }}>Watch v{latest.version} · {latest.quality === 'final' ? 'Final' : 'Preview'}</Text>
            <Text style={{ color: t.textSecondary }}>{formatSeconds(latest.duration_s ?? 0)} · tap to play, save or share</Text>
          </>
        ) : null}
        {working ? (
          <View style={{ gap: Spacing.one }}>
            <Text style={{ color: t.text, fontWeight: '600' }}>Rendering v{working.version} · {working.quality === 'final' ? 'Final' : 'Preview'}</Text>
            <ProgressBar value={working.progress ?? 0} label={working.stage ?? 'Waiting to start'} />
          </View>
        ) : null}
      </View>
    </Card>
  );
}

// brief ---------------------------------------------------------------------------

function Brief({ p }: { p: Project }) {
  const t = useTheme();
  const styles_ = useQuery({ queryKey: ['styles'], queryFn: api.styles });
  const style = styles_.data?.find((s) => s.id === p.style_id);
  const lang = { en: 'English', hi: 'Hindi', hinglish: 'Hinglish' }[p.language ?? 'en'] ?? p.language;
  const stats = Object.entries(p.stats ?? {});
  return (
    <Card>
      <Text style={{ color: t.textSecondary }}>
        Style <Text style={{ color: t.text }}>{p.style_id ? (style?.profile?.name ?? style?.name ?? '…') : 'none'}</Text> · {lang}
      </Text>
      {p.script ? <Text style={{ color: t.text }} numberOfLines={4}>{p.script}</Text> : null}
      {stats.length ? <Text style={{ color: t.textSecondary }}>{stats.map(([k, v]) => `${k} ${v}`).join(' · ')}</Text> : null}
    </Card>
  );
}

// clips --------------------------------------------------------------------------

function Clips({ p, uploads, setUploads }: { p: Project; uploads: LocalUpload[]; setUploads: React.Dispatch<React.SetStateAction<LocalUpload[]>> }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const room = MAX_CLIPS - p.clips.length - uploads.filter((u) => !u.error).length;
  const locked = p.status === 'analyzing' || p.status === 'rendering';
  const refresh = () => qc.invalidateQueries({ queryKey: ['project', p.id] });

  async function addClips() {
    setError(null);
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      setError('Allow access to your videos to add clips.');
      return;
    }
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['videos'], allowsEditing: false, allowsMultipleSelection: true, selectionLimit: room, orderedSelection: true,
    });
    if (res.canceled || !res.assets?.length) return;
    const picked = res.assets.slice(0, room);
    const tooLong = picked.filter((a) => a.duration && a.duration / 1000 > MAX_CLIP_SECONDS);
    if (tooLong.length) setError(`${tooLong.length} clip(s) longer than 5 minutes were skipped.`);
    const ok = picked.filter((a) => !tooLong.includes(a));
    const items = ok.map((a, i) => ({ key: `${Date.now()}-${i}`, name: a.fileName ?? `clip ${i + 1}`, progress: 0 }));
    setUploads((u) => [...u, ...items]);

    const setItem = (key: string, patch: Partial<LocalUpload>) => setUploads((u) => u.map((x) => (x.key === key ? { ...x, ...patch } : x)));

    // 1. book every clip's slot first, one by one: positions C1, C2... follow the order picked
    const jobs: { key: string; uri: string; ticket: Awaited<ReturnType<typeof api.clipUploadUrl>> }[] = [];
    for (const [i, a] of ok.entries()) {
      try {
        const ticket = await api.clipUploadUrl(p.id, a.fileName ?? 'clip.mp4', a.mimeType ?? 'video/mp4', a.fileSize ?? undefined);
        jobs.push({ key: items[i].key, uri: a.uri, ticket });
      } catch (e) {
        setItem(items[i].key, { error: e instanceof Error ? e.message : 'Upload failed' });
      }
    }
    refresh();

    // 2. upload 3 at a time - faster than one by one without starving a phone connection
    let next = 0;
    const worker = async () => {
      while (next < jobs.length) {
        const { key, uri, ticket } = jobs[next++];
        try {
          await uploadWithProgress(uri, ticket.upload_url, ticket.headers, (progress) => setItem(key, { progress }));
          await api.completeClip(p.id, ticket.clip_id);
          setUploads((u) => u.filter((x) => x.key !== key));
          refresh();
        } catch (e) {
          setItem(key, { error: e instanceof Error ? e.message : 'Upload failed' });
          refresh();
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(PARALLEL_UPLOADS, jobs.length) }, worker));
  }

  const move = useMutation({
    mutationFn: (ids: string[]) => api.reorderClips(p.id, ids),
    onSuccess: refresh,
  });
  const swap = (i: number, j: number) => {
    const ids = p.clips.map((c) => c.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    move.mutate(ids);
  };

  return (
    <>
      <SectionTitle>
        Clips · {p.clips.length}/{MAX_CLIPS}
        {p.total_duration_s ? ` · ${formatSeconds(p.total_duration_s)}` : ''}
      </SectionTitle>
      {p.clips.length === 0 && uploads.length === 0 ? (
        <Text style={{ color: t.textSecondary, fontSize: 15 }}>
          Pick the clips in the order you want them. Shoot vertically; Raw2Reel trims the dead air.
        </Text>
      ) : null}
      {p.clips.map((c, i) => (
        <ClipRow key={c.id} c={c} index={i} count={p.clips.length} projectId={p.id} locked={locked || move.isPending}
          onUp={() => swap(i, i - 1)} onDown={() => swap(i, i + 1)} />
      ))}
      {uploads.map((u) => (
        <Card key={u.key} style={styles.clipRow}>
          <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]} />
          <View style={{ flex: 1, gap: Spacing.one }}>
            <Text style={{ color: t.text, fontWeight: '600' }} numberOfLines={1}>{u.name}</Text>
            {u.error ? (
              <Text style={{ color: t.danger, fontSize: 13 }}>{u.error}</Text>
            ) : (
              <>
                <Text style={{ color: t.textSecondary, fontSize: 13 }}>Uploading… {Math.round(u.progress * 100)}%</Text>
                <View style={[styles.track, { backgroundColor: t.backgroundSelected }]}>
                  <View style={[styles.fill, { width: `${u.progress * 100}%`, backgroundColor: t.accent }]} />
                </View>
              </>
            )}
          </View>
          {u.error ? <Button label="Dismiss" kind="ghost" style={styles.small} onPress={() => setUploads((x) => x.filter((y) => y.key !== u.key))} /> : null}
        </Card>
      ))}
      {error ? <Text style={{ color: t.danger }}>{error}</Text> : null}
      {room > 0 && !locked ? <Button label={p.clips.length ? '+ Add more clips' : '+ Add clips'} kind="secondary" onPress={addClips} /> : null}
    </>
  );
}

function ClipRow({ c, index, count, projectId, locked, onUp, onDown }: {
  c: Clip; index: number; count: number; projectId: string; locked: boolean; onUp: () => void; onDown: () => void;
}) {
  const t = useTheme();
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.deleteClip(projectId, c.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['project', projectId] }),
  });
  const line =
    c.status === 'failed' ? (c.error ?? 'Failed') :
    c.status === 'pending' ? 'Waiting for the upload to finish…' :
    c.status !== 'ready' ? 'Checking the video…' :
    c.analysis_status === 'failed' ? 'Analysis failed' :
    c.analysis_status !== 'ready' ? `${formatSeconds(c.duration_s ?? 0)} · analysing…` :
    `${formatSeconds(c.duration_s ?? 0)} · ${c.has_speech ? `speech (${c.spoken_language ?? '?'})` : 'no speech'}`;

  return (
    <Card style={styles.clipRow}>
      <Text style={[styles.alias, { color: t.textSecondary }]}>C{index + 1}</Text>
      <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]}>
        {c.thumbnail_url ? <Image source={{ uri: c.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ color: t.text, fontWeight: '600' }} numberOfLines={1}>{c.original_filename ?? 'Clip'}</Text>
        <Text style={{ color: c.status === 'failed' ? t.danger : t.textSecondary, fontSize: 13 }} numberOfLines={2}>{line}</Text>
        {c.transcript_text ? (
          <Text style={{ color: t.textSecondary, fontSize: 12, fontStyle: 'italic' }} numberOfLines={1}>“{c.transcript_text}”</Text>
        ) : null}
      </View>
      {!locked ? (
        <View style={styles.actions}>
          <View style={styles.arrows}>
            <Arrow label="↑" disabled={index === 0} onPress={onUp} />
            <Arrow label="↓" disabled={index === count - 1} onPress={onDown} />
          </View>
          <Button label="Remove" kind="ghost" style={styles.small} onPress={() => del.mutate()} loading={del.isPending} />
        </View>
      ) : null}
    </Card>
  );
}

function Arrow({ label, disabled, onPress }: { label: string; disabled: boolean; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable accessibilityLabel={label === '↑' ? 'Move up' : 'Move down'} disabled={disabled} onPress={onPress}
      style={[styles.arrow, { borderColor: t.border, opacity: disabled ? 0.3 : 1 }]}>
      <Text style={{ color: t.text, fontSize: 16 }}>{label}</Text>
    </Pressable>
  );
}

// plan ----------------------------------------------------------------------------

function Plan({ p, uploading }: { p: Project; uploading: boolean }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const gen = useMutation({
    mutationFn: () => api.generatePlan(p.id),
    onSuccess: () => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ['project', p.id] });
      qc.invalidateQueries({ queryKey: ['projects'] });
      qc.invalidateQueries({ queryKey: ['ai-usage'] });
    },
  });
  const busy = p.clips.some(clipBusy) || uploading;
  const hasPlan = !!p.plan;

  if (p.status === 'analyzing') {
    return (
      <Card>
        <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }}>Editing your reel…</Text>
        <Text style={{ color: t.textSecondary }}>Picking the best moments and writing the captions. About half a minute.</Text>
      </Card>
    );
  }
  return (
    <View style={{ gap: Spacing.two, marginTop: Spacing.two }}>
      {p.status === 'failed' && p.error ? <Text style={{ color: t.danger }}>{p.error}</Text> : null}
      {hasPlan && p.plan_timeline ? (
        <Card>
          <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }}>Edit plan ready · {formatSeconds(p.plan_timeline.total_s)}</Text>
          <Text style={{ color: t.textSecondary }}>{String((p.plan as { summary?: string }).summary ?? '')}</Text>
          {p.plan_warnings.length ? (
            <Text style={{ color: t.textSecondary, fontSize: 13 }}>{p.plan_warnings.length} automatic fix{p.plan_warnings.length === 1 ? '' : 'es'} applied</Text>
          ) : null}
          <Button label="Review, edit & render" onPress={() => router.push({ pathname: '/reel/plan/[id]', params: { id: p.id } })} />
        </Card>
      ) : null}
      {confirming ? (
        <ConfirmAI
          title={hasPlan ? 'Write a new edit plan?' : 'Edit this reel?'}
          note={hasPlan ? 'The current plan will be replaced.' : undefined}
          confirmLabel={hasPlan ? 'Rewrite it' : 'Edit it'}
          onConfirm={() => gen.mutate()}
          onCancel={() => setConfirming(false)}
          loading={gen.isPending}
          error={gen.isError ? gen.error.message : null}
        />
      ) : (
        <>
          <Text style={{ color: t.textSecondary, fontSize: 14 }}>
            {busy ? 'Waiting for your clips to finish processing…' : p.clips.length === 0 ? 'Add clips to start.' : `${p.clips.length} clip${p.clips.length === 1 ? '' : 's'} ready.`}
          </Text>
          <Button label={hasPlan ? 'Rewrite the edit plan' : 'Edit my reel'} kind={hasPlan ? 'secondary' : 'primary'}
            onPress={() => setConfirming(true)} disabled={busy || !p.analysis_ready || p.status === 'rendering'} />
        </>
      )}
    </View>
  );
}

function DeleteReel({ id }: { id: string }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [sure, setSure] = useState(false);
  const del = useMutation({
    mutationFn: () => api.deleteProject(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] });
      if (router.canGoBack()) router.back();
      else router.replace('/');
    },
  });
  return (
    <View style={{ marginTop: Spacing.four }}>
      {sure ? (
        <View style={{ flexDirection: 'row', gap: Spacing.two }}>
          <Button label="Keep it" kind="secondary" onPress={() => setSure(false)} style={{ flex: 1 }} />
          <Button label="Delete reel" onPress={() => del.mutate()} loading={del.isPending} style={{ flex: 1, backgroundColor: t.danger }} />
        </View>
      ) : (
        <Button label="Delete this reel" kind="ghost" onPress={() => setSure(true)} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  clipRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, padding: Spacing.two },
  alias: { width: 24, fontSize: 12, fontWeight: '700', textAlign: 'center' },
  thumb: { width: 54, height: 96, borderRadius: Radius.sm, overflow: 'hidden' },
  actions: { alignItems: 'flex-end', gap: Spacing.one },
  arrows: { flexDirection: 'row', gap: Spacing.one },
  arrow: { width: 32, height: 32, borderRadius: Radius.sm, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  small: { minHeight: 32, paddingHorizontal: Spacing.two },
  track: { height: 6, borderRadius: Radius.pill, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: Radius.pill },
});
