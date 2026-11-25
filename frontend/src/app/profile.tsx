/** Profile: who is signed in, what the editor has learnt (creator memory), today's AI usage
 * against the daily limit, server, sign out. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { Button, Card, Screen } from '@/components/ui';
import { Radius } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { API_URL } from '@/lib/config';
import { useSession } from '@/lib/session';
import type { Lesson } from '@/lib/types';

export default function ProfileScreen() {
  const t = useTheme();
  const { me, signOut } = useSession();
  const usage = useQuery({ queryKey: ['ai-usage'], queryFn: api.aiUsage });
  const lessons = useQuery({ queryKey: ['lessons'], queryFn: api.lessons });

  const used = usage.data?.calls_last_24h ?? 0;
  const limit = usage.data?.daily_limit ?? 0;
  const pct = limit ? Math.min(1, used / limit) : 0;

  return (
    <Screen title="Profile" onRefresh={() => { usage.refetch(); lessons.refetch(); }}>
      <Card>
        <Text style={[styles.name, { color: t.text }]}>{me?.name ?? 'Creator'}</Text>
        <Text style={[styles.meta, { color: t.textSecondary }]}>{me?.email}</Text>
      </Card>

      <Learnt lessons={lessons.data} loading={lessons.isPending} />

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

/** Creator memory: every lesson, newest first. Switch one off, forget it, or teach a new one. */
function Learnt({ lessons, loading }: { lessons?: Lesson[]; loading: boolean }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ['lessons'] });
  const toggle = useMutation({ mutationFn: (l: Lesson) => api.updateLesson(l.id, { active: !l.active }), onSuccess: refresh });
  const forget = useMutation({ mutationFn: (id: string) => api.forgetLesson(id), onSuccess: refresh });
  const add = useMutation({
    mutationFn: () => api.addLesson(text.trim()),
    onSuccess: () => { setText(''); setError(null); refresh(); },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Card style={{ gap: 12 }}>
      <Text style={[styles.label, { color: t.textSecondary }]}>🧠 What I've learnt</Text>
      <Text style={[styles.meta, { color: t.textSecondary }]}>
        When you ask for a change that you'd want every time, I remember it and follow it in your next reels.
      </Text>
      {loading ? <Text style={{ color: t.textSecondary }}>…</Text> : null}
      {lessons && !lessons.length ? (
        <Text style={[styles.meta, { color: t.textSecondary }]}>Nothing yet. Ask for a change on a reel, or add one below.</Text>
      ) : null}
      {lessons?.map((l) => (
        <View key={l.id} style={[styles.lesson, { borderColor: t.border, opacity: l.active ? 1 : 0.5 }]}>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={{ color: t.text, fontWeight: '600' }}>{l.text}</Text>
            <Text style={{ color: t.textSecondary, fontSize: 12 }}>
              {l.applies_to === 'all' ? 'All reels' : `${l.applies_to} reels`}
              {l.request ? ` · from “${l.request.length > 50 ? `${l.request.slice(0, 50)}…` : l.request}”` : ''}
            </Text>
          </View>
          <Switch value={l.active} onValueChange={() => toggle.mutate(l)} />
          <Pressable onPress={() => forget.mutate(l.id)} hitSlop={8}>
            <Text style={{ color: t.danger, fontSize: 18 }}>✕</Text>
          </Pressable>
        </View>
      ))}
      <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="Teach me one, e.g. Always end with my handle"
          placeholderTextColor={t.textSecondary}
          style={[styles.input, { color: t.text, borderColor: t.border }]}
          onSubmitEditing={() => text.trim().length >= 3 && add.mutate()}
        />
        <Button label="Add" kind="secondary" onPress={() => add.mutate()} disabled={text.trim().length < 3} loading={add.isPending} />
      </View>
      {error ? <Text style={{ color: t.danger, fontSize: 13 }}>{error}</Text> : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  lesson: { flexDirection: 'row', alignItems: 'center', gap: 10, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 10 },
  input: { flex: 1, borderWidth: 1, borderRadius: Radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  name: { fontSize: 20, fontWeight: '700' },
  label: { fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1 },
  big: { fontSize: 28, fontWeight: '700' },
  meta: { fontSize: 14, lineHeight: 20 },
  track: { height: 8, borderRadius: Radius.pill, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: Radius.pill },
});
