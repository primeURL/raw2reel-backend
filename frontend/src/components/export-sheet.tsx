/** Export: choose quality -> big progress -> Watch / Save / Share. Rendering is free (no AI). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Sheet } from '@/components/sheet';
import { Button, formatSeconds } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { saveToGallery, shareVideo } from '@/lib/share';
import type { Render } from '@/lib/types';

const working = (r: Render) => r.status === 'pending' || r.status === 'processing';

export function useRenders(projectId: string) {
  return useQuery({
    queryKey: ['renders', projectId],
    queryFn: () => api.renders(projectId),
    refetchInterval: (q) => (q.state.data?.some(working) ? 1500 : false),
  });
}

export function ExportSheet({ projectId, title, open, onClose }: { projectId: string; title: string; open: boolean; onClose: () => void }) {
  const t = useTheme();
  const qc = useQueryClient();
  const renders = useRenders(projectId);
  const [mine, setMine] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: (quality: 'preview' | 'final') => api.render(projectId, quality),
    onSuccess: (r) => {
      setMine(r.id);
      qc.invalidateQueries({ queryKey: ['renders', projectId] });
      qc.invalidateQueries({ queryKey: ['project', projectId] });
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
  const list = renders.data ?? [];
  const active = list.find((r) => r.id === mine) ?? list.find(working);
  const close = () => {
    if (active && !working(active)) setMine(null);
    onClose();
  };

  return (
    <Sheet open={open} onClose={close} title={active && working(active) ? 'Exporting…' : active?.status === 'ready' ? 'Your reel is ready' : 'Export'}>
      {active && working(active) ? (
        <Progress r={active} />
      ) : active?.status === 'ready' ? (
        <Ready r={active} title={title} onWatch={() => { close(); router.push({ pathname: '/reel/watch/[renderId]', params: { renderId: active.id, projectId } }); }} onAgain={() => setMine(null)} />
      ) : (
        <>
          {active?.status === 'failed' ? <Text style={{ color: t.danger }}>The last export failed: {active.error ?? 'unknown error'}</Text> : null}
          <Option icon="⚡" title="Quick preview" body="540p in a few seconds. To check the edit." loading={start.isPending && start.variables === 'preview'} onPress={() => start.mutate('preview')} />
          <Option icon="✨" title="Final 1080p" body="Full quality, ready to post." primary loading={start.isPending && start.variables === 'final'} onPress={() => start.mutate('final')} />
          {start.isError ? <Text style={{ color: t.danger }}>{start.error.message}</Text> : null}
          <Text style={{ color: t.textSecondary, fontSize: 13 }}>Exporting is free and never replaces an earlier version.</Text>
        </>
      )}
    </Sheet>
  );
}

function Option({ icon, title, body, onPress, loading, primary }: { icon: string; title: string; body: string; onPress: () => void; loading?: boolean; primary?: boolean }) {
  const t = useTheme();
  return (
    <Pressable onPress={loading ? undefined : onPress} style={({ pressed }) => [styles.option, { borderColor: primary ? t.accent : t.border, backgroundColor: primary ? t.accent + '18' : t.background, opacity: pressed || loading ? 0.7 : 1 }]}>
      <Text style={{ fontSize: 28 }}>{icon}</Text>
      <View style={{ flex: 1 }}>
        <Text style={{ color: t.text, fontSize: 17, fontWeight: '700' }}>{loading ? 'Starting…' : title}</Text>
        <Text style={{ color: t.textSecondary }}>{body}</Text>
      </View>
      <Text style={{ color: primary ? t.accent : t.textSecondary, fontSize: 20 }}>›</Text>
    </Pressable>
  );
}

function Progress({ r }: { r: Render }) {
  const t = useTheme();
  const pct = Math.round((r.progress ?? 0) * 100);
  return (
    <View style={{ alignItems: 'center', gap: Spacing.three, paddingVertical: Spacing.four }}>
      <Text style={{ color: t.text, fontSize: 56, fontWeight: '800', letterSpacing: -1 }}>{pct}%</Text>
      <View style={[styles.track, { backgroundColor: t.backgroundSelected }]}>
        <View style={[styles.fill, { width: `${pct}%`, backgroundColor: t.accent }]} />
      </View>
      <Text style={{ color: t.textSecondary, fontSize: 15 }}>{r.stage ?? 'Waiting to start'} · {r.quality === 'final' ? 'Final 1080p' : 'Quick preview'}</Text>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>You can close this. It keeps going.</Text>
    </View>
  );
}

function Ready({ r, title, onWatch, onAgain }: { r: Render; title: string; onWatch: () => void; onAgain: () => void }) {
  const t = useTheme();
  const [note, setNote] = useState<string | null>(null);
  const fileName = `${title.replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase() || 'reel'}-v${r.version}.mp4`;
  const save = useMutation({ mutationFn: () => saveToGallery(r.video_url!, fileName), onSuccess: setNote, onError: (e) => setNote(e.message) });
  const share = useMutation({ mutationFn: () => shareVideo(r.video_url!, fileName), onSuccess: setNote, onError: (e) => setNote(e.message) });
  const failed = (r.checks ?? []).filter((c) => !c.ok);
  return (
    <View style={{ gap: Spacing.three }}>
      <Pressable onPress={onWatch} style={styles.readyRow}>
        <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]}>
          {r.thumbnail_url ? <Image source={{ uri: r.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
          <View style={styles.play}><Text style={{ color: '#fff', fontSize: 22 }}>▶</Text></View>
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={{ color: t.text, fontSize: 17, fontWeight: '700' }}>Version {r.version} · {r.quality === 'final' ? 'Final 1080p' : 'Preview'}</Text>
          <Text style={{ color: t.textSecondary }}>{formatSeconds(r.duration_s ?? 0)} · made in {Math.round(r.seconds_taken ?? 0)}s</Text>
          {r.checks?.length ? (
            <Text style={{ color: failed.length ? t.danger : t.success, fontSize: 13 }}>
              {failed.length ? `✗ ${failed.map((c) => c.name).join(', ')}` : `✓ All ${r.checks.length} checks passed`}
            </Text>
          ) : null}
        </View>
      </Pressable>
      <View style={styles.row}>
        <Button label="Save" kind="secondary" style={{ flex: 1 }} loading={save.isPending} onPress={() => { setNote(null); save.mutate(); }} />
        <Button label="Share" style={{ flex: 1 }} loading={share.isPending} onPress={() => { setNote(null); share.mutate(); }} />
      </View>
      {note ? <Text style={{ color: t.textSecondary, textAlign: 'center' }}>{note}</Text> : null}
      <Button label="Watch it" kind="secondary" onPress={onWatch} />
      {r.quality === 'preview' ? <Button label="Export the final 1080p" kind="ghost" onPress={onAgain} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  option: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, borderWidth: 1.5, borderRadius: Radius.lg, padding: Spacing.three },
  track: { width: '100%', height: 10, borderRadius: Radius.pill, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: Radius.pill },
  readyRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three },
  thumb: { width: 72, height: 128, borderRadius: Radius.md, overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  play: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(0,0,0,0.5)', alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', gap: Spacing.two },
});
