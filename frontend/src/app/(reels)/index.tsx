/** Reels: the user's projects, newest first. */

import { useQuery } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Loading, Message, Screen, StatusChip, formatSeconds } from '@/components/ui';
import { useSession } from '@/lib/session';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { ProjectSummary } from '@/lib/types';

const BUSY = new Set(['analyzing', 'rendering']);

export default function ReelsScreen() {
  const { me } = useSession();
  const first = me?.name?.split(' ')[0];
  const t = useTheme();
  const q = useQuery({
    queryKey: ['projects'],
    queryFn: api.projects,
    // keep polling while anything is working, so statuses update by themselves
    refetchInterval: (query) => (query.state.data?.some((p) => BUSY.has(p.status)) ? 4000 : false),
  });

  return (
    <Screen
      title={first ? `Hi ${first}` : 'Reels'}
      subtitle="Drop in raw clips. Get a reel back."
      onRefresh={q.refetch}
      right={<Button label="+ New" onPress={() => router.push('/reel/new')} style={{ minHeight: 40 }} />}>
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <Message title="Couldn't load your reels" body={q.error.message} action={<Button label="Try again" kind="secondary" onPress={() => q.refetch()} />} />
      ) : (
        <>
          <Starters />
          {q.data.length ? <Text style={[styles.section, { color: t.textSecondary }]}>Your reels</Text> : null}
          {q.data.map((p) => <ProjectRow key={p.id} p={p} />)}
        </>
      )}
    </Screen>
  );
}

/** Three ways in, like a chat app's suggestions. */
function Starters() {
  const t = useTheme();
  const items = [
    { icon: '🎬', title: 'Edit my clips', body: 'Raw clips in, reel out', go: () => router.push('/reel/new'), primary: true },
    { icon: '🔗', title: "Learn a reel's style", body: 'Paste reels you love', go: () => router.push('/styles/new') },
    { icon: '🎨', title: 'My looks', body: 'Styles you have taught it', go: () => router.push('/styles') },
  ];
  return (
    <View style={styles.starters}>
      {items.map((x) => (
        <Pressable key={x.title} onPress={x.go} style={({ pressed }) => [styles.starter, {
          backgroundColor: x.primary ? t.accent : t.backgroundElement, borderColor: x.primary ? t.accent : t.border, opacity: pressed ? 0.85 : 1,
        }]}>
          <Text style={{ fontSize: 26 }}>{x.icon}</Text>
          <Text style={{ color: x.primary ? t.onAccent : t.text, fontWeight: '800', fontSize: 15 }}>{x.title}</Text>
          <Text style={{ color: x.primary ? t.onAccent : t.textSecondary, fontSize: 12, opacity: 0.9 }}>{x.body}</Text>
        </Pressable>
      ))}
    </View>
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
  section: { fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1, marginTop: Spacing.two },
  starters: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  starter: { flexGrow: 1, flexBasis: '30%', minWidth: 140, borderWidth: 1, borderRadius: Radius.lg, padding: Spacing.three, gap: 2 },
});
