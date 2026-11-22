/** Reels: the user's projects, newest first. */

import { useQuery } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, Loading, Message, Screen, StatusChip, formatSeconds } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { ProjectSummary } from '@/lib/types';

const BUSY = new Set(['analyzing', 'rendering']);

export default function ReelsScreen() {
  const q = useQuery({
    queryKey: ['projects'],
    queryFn: api.projects,
    // keep polling while anything is working, so statuses update by themselves
    refetchInterval: (query) => (query.state.data?.some((p) => BUSY.has(p.status)) ? 4000 : false),
  });

  return (
    <Screen
      title="Reels"
      subtitle="Your edits, newest first"
      onRefresh={q.refetch}
      right={<Button label="+ New" onPress={() => router.push('/reel/new')} style={{ minHeight: 40 }} />}>
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <Message title="Couldn't load your reels" body={q.error.message} action={<Button label="Try again" kind="secondary" onPress={() => q.refetch()} />} />
      ) : q.data.length === 0 ? (
        <Message title="No reels yet" body="Pick a few clips from your phone and Raw2Reel edits them in your style." action={<Button label="Make your first reel" onPress={() => router.push('/reel/new')} />} />
      ) : (
        q.data.map((p) => <ProjectRow key={p.id} p={p} />)
      )}
    </Screen>
  );
}

function ProjectRow({ p }: { p: ProjectSummary }) {
  const t = useTheme();
  return (
    <Card style={styles.row} onPress={() => router.push({ pathname: '/reel/[id]', params: { id: p.id } })}>
      <View style={[styles.cover, { backgroundColor: t.backgroundSelected }]}>
        {p.cover_url ? <Image source={{ uri: p.cover_url }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} /> : null}
      </View>
      <View style={styles.info}>
        <Text style={[styles.title, { color: t.text }]} numberOfLines={2}>
          {p.title}
        </Text>
        <Text style={[styles.meta, { color: t.textSecondary }]}>
          {p.clip_count} clip{p.clip_count === 1 ? '' : 's'} · {formatSeconds(p.total_duration_s)} of footage
        </Text>
        <StatusChip status={p.status} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, padding: Spacing.two },
  cover: { width: 72, height: 128, borderRadius: Radius.md, overflow: 'hidden' },
  info: { flex: 1, gap: Spacing.one },
  title: { fontSize: 17, fontWeight: '600' },
  meta: { fontSize: 14 },
});
