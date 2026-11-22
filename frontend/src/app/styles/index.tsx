/** Styles: what Raw2Reel learned from the user's reference reels. */

import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, Loading, Message, Screen, StatusChip } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { Style } from '@/lib/types';

export default function StylesScreen() {
  const q = useQuery({
    queryKey: ['styles'],
    queryFn: api.styles,
    refetchInterval: (query) => (query.state.data?.some((s) => s.status === 'analyzing') ? 4000 : false),
  });
  const newStyle = () => router.push('/styles/new');

  return (
    <Screen
      title="Styles"
      subtitle="Learned from reels you love"
      onRefresh={q.refetch}
      right={<Button label="+ New" onPress={newStyle} style={{ minHeight: 40 }} />}>
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <Message title="Couldn't load your styles" body={q.error.message} action={<Button label="Try again" kind="secondary" onPress={() => q.refetch()} />} />
      ) : q.data.length === 0 ? (
        <Message
          title="No style yet"
          body="Share 3-4 reels whose editing you love - Instagram links or saved videos - and Raw2Reel learns the style."
          action={<Button label="Create your style" onPress={newStyle} />}
        />
      ) : (
        q.data.map((s) => <StyleRow key={s.id} s={s} />)
      )}
    </Screen>
  );
}

function StyleRow({ s }: { s: Style }) {
  const t = useTheme();
  const accent = s.profile?.look?.accent_color ?? t.accent;
  return (
    <Card onPress={() => router.push({ pathname: '/styles/[id]', params: { id: s.id } })}>
      <View style={styles.top}>
        <View style={[styles.swatch, { backgroundColor: accent }]} />
        <Text style={[styles.name, { color: t.text }]}>{s.profile?.name ?? s.name}</Text>
        <StatusChip status={s.status} />
      </View>
      {s.profile?.summary ? (
        <Text style={[styles.summary, { color: t.textSecondary }]} numberOfLines={3}>
          {s.profile.summary}
        </Text>
      ) : null}
      {s.status === 'failed' && s.error ? <Text style={{ color: t.danger }}>{s.error}</Text> : null}
      <Text style={[styles.meta, { color: t.textSecondary }]}>
        {s.reference_count ? `${s.references_ready}/${s.reference_count} reference reels ready` : 'No reference reels yet'}
      </Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  swatch: { width: 14, height: 14, borderRadius: Radius.pill },
  name: { flex: 1, fontSize: 18, fontWeight: '600' },
  summary: { fontSize: 15, lineHeight: 21 },
  meta: { fontSize: 13 },
});
