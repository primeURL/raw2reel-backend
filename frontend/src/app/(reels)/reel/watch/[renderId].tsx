/** Watch a rendered version in the app, switch between versions, save it to the gallery or share it. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEvent } from 'expo';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Choice, Loading, Message, Screen, SectionTitle, formatSeconds } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { saveToGallery, shareVideo } from '@/lib/share';
import type { Render } from '@/lib/types';

export default function WatchScreen() {
  const { renderId, projectId } = useLocalSearchParams<{ renderId: string; projectId: string }>();
  const renders = useQuery({ queryKey: ['renders', projectId], queryFn: () => api.renders(projectId) });
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.project(projectId) });

  if (renders.isPending) return <Loading />;
  if (renders.isError) return <Message title="Couldn't load this video" body={renders.error.message} />;
  const ready = renders.data.filter((r) => r.status === 'ready' && r.video_url);
  const current = ready.find((r) => r.id === renderId) ?? ready[0];
  if (!current) return <Message title="No finished version yet" body="Render a preview or final from the plan first." />;

  return (
    <>
      <Stack.Screen options={{ title: project.data?.title ?? 'Watch' }} />
      {/* key: a fresh player per version, so switching never shows the old video */}
      <Player key={current.id} r={current} projectId={projectId} title={project.data?.title ?? 'reel'} versions={ready} />
    </>
  );
}

function Player({ r, projectId, title, versions }: { r: Render; projectId: string; title: string; versions: Render[] }) {
  const t = useTheme();
  const qc = useQueryClient();
  const player = useVideoPlayer(r.video_url!, (p) => {
    p.loop = true;
    p.play();
  });
  const { status, error } = useEvent(player, 'statusChange', { status: player.status, error: undefined });
  const [note, setNote] = useState<string | null>(null);
  const fileName = `${title.replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase() || 'reel'}-v${r.version}.mp4`;

  const save = useMutation({ mutationFn: () => saveToGallery(r.video_url!, fileName), onSuccess: setNote, onError: (e) => setNote(e.message) });
  const share = useMutation({ mutationFn: () => shareVideo(r.video_url!, fileName), onSuccess: setNote, onError: (e) => setNote(e.message) });
  const del = useMutation({
    mutationFn: () => api.deleteRender(projectId, r.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['renders', projectId] });
      const other = versions.find((v) => v.id !== r.id);
      if (other) router.setParams({ renderId: other.id });
      else router.back();
    },
  });

  return (
    <Screen title={`Version ${r.version}`} subtitle={`${r.quality === 'final' ? 'Final 1080×1920' : 'Quick preview'} · ${formatSeconds(r.duration_s ?? 0)}`}>
      <View style={[styles.frame, { backgroundColor: '#000', borderColor: t.border }]}>
        {/* explicit 100% size: on web, absoluteFill alone leaves <video> at its intrinsic 1080x1920 */}
        <VideoView player={player} style={styles.video} contentFit="contain" nativeControls fullscreenOptions={{ enable: true }} />
      </View>
      {status === 'error' ? <Text style={{ color: t.danger }}>Couldn&apos;t play this video{error?.message ? `: ${error.message}` : ''}</Text> : null}

      <View style={styles.row}>
        <Button label="Save" kind="secondary" style={{ flex: 1 }} loading={save.isPending} onPress={() => { setNote(null); save.mutate(); }} />
        <Button label="Share" style={{ flex: 1 }} loading={share.isPending} onPress={() => { setNote(null); share.mutate(); }} />
      </View>
      {note ? <Text style={{ color: t.textSecondary, textAlign: 'center' }}>{note}</Text> : null}
      {r.quality === 'preview' ? (
        <Text style={{ color: t.textSecondary, fontSize: 13, textAlign: 'center' }}>
          This is a quick preview (540×960). Render the final from the plan before posting.
        </Text>
      ) : null}

      {versions.length > 1 ? (
        <>
          <SectionTitle>Versions</SectionTitle>
          <View style={styles.choices}>
            {versions.map((v) => (
              <Choice key={v.id} label={`v${v.version} · ${v.quality === 'final' ? 'Final' : 'Preview'}`} selected={v.id === r.id}
                onPress={() => router.setParams({ renderId: v.id })} />
            ))}
          </View>
        </>
      ) : null}

      <Button label="Delete this version" kind="ghost" loading={del.isPending} onPress={() => del.mutate()} style={{ marginTop: Spacing.three }} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  frame: { width: '100%', maxWidth: 380, aspectRatio: 9 / 16, alignSelf: 'center', borderRadius: Radius.lg, overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth },
  video: { position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' },
  row: { flexDirection: 'row', gap: Spacing.two },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
});
