/** Profile: who is signed in, today's AI usage against the daily limit, server, sign out. */

import { useQuery } from '@tanstack/react-query';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, Screen } from '@/components/ui';
import { Radius } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { API_URL } from '@/lib/config';
import { useSession } from '@/lib/session';

export default function ProfileScreen() {
  const t = useTheme();
  const { me, signOut } = useSession();
  const usage = useQuery({ queryKey: ['ai-usage'], queryFn: api.aiUsage });

  const used = usage.data?.calls_last_24h ?? 0;
  const limit = usage.data?.daily_limit ?? 0;
  const pct = limit ? Math.min(1, used / limit) : 0;

  return (
    <Screen title="Profile" onRefresh={usage.refetch}>
      <Card>
        <Text style={[styles.name, { color: t.text }]}>{me?.name ?? 'Creator'}</Text>
        <Text style={[styles.meta, { color: t.textSecondary }]}>{me?.email}</Text>
      </Card>

      <Card>
        <Text style={[styles.label, { color: t.textSecondary }]}>AI edits today</Text>
        <Text style={[styles.big, { color: t.text }]}>
          {usage.isPending ? '…' : `${used} / ${limit}`}
        </Text>
        <View style={[styles.track, { backgroundColor: t.backgroundSelected }]}>
          <View style={[styles.fill, { width: `${pct * 100}%`, backgroundColor: pct >= 1 ? t.danger : t.accent }]} />
        </View>
        <Text style={[styles.meta, { color: t.textSecondary }]}>
          Style analysis, answers and edit plans count here. Rendering is free.
          {usage.data ? `  Spent so far: $${usage.data.all_time_usd.toFixed(2)}` : ''}
        </Text>
      </Card>

      <Card>
        <Text style={[styles.label, { color: t.textSecondary }]}>Server</Text>
        <Text style={[styles.meta, { color: t.text }]}>{API_URL}</Text>
      </Card>

      <Button label="Sign out" kind="secondary" onPress={signOut} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  name: { fontSize: 20, fontWeight: '700' },
  label: { fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1 },
  big: { fontSize: 28, fontWeight: '700' },
  meta: { fontSize: 14, lineHeight: 20 },
  track: { height: 8, borderRadius: Radius.pill, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: Radius.pill },
});
