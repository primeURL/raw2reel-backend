/** Pick a look by seeing it: one swipeable card per learned style (frames from its reference reels),
 * a plain "Clean" look, a card to learn a new one from reels you love, and a row of ready-made
 * templates (tapping one adds it to your styles once, then selects it). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { Style, Template } from '@/lib/types';

const CARD_W = 150;

export function LookPicker({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const t = useTheme();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['styles'], queryFn: api.styles });
  const tpl = useQuery({ queryKey: ['templates'], queryFn: api.templates, staleTime: 10 * 60_000 });
  const ready = (q.data ?? []).filter((s) => s.status === 'ready');
  const learned = ready.filter((s) => !s.template);
  const fromTemplate = (id: string) => ready.find((s) => s.template === id);
  const use = useMutation({
    mutationFn: (tid: string) => api.useTemplate(tid),
    onSuccess: (style) => {
      qc.invalidateQueries({ queryKey: ['styles'] });
      onChange(style.id);
    },
  });
  return (
    <View style={{ gap: Spacing.two }}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {learned.map((s) => <StyleCard key={s.id} s={s} selected={value === s.id} onPress={() => onChange(s.id)} />)}
        <PlainCard selected={value === null} onPress={() => onChange(null)} />
        <LearnCard />
      </ScrollView>
      {tpl.data?.length ? (
        <>
          <Text style={{ color: t.textSecondary, fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1 }}>
            Ready-made templates
          </Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
            {tpl.data.map((x) => {
              const mine = fromTemplate(x.id);
              return (
                <TemplateCard key={x.id} x={x} selected={!!mine && value === mine.id} busy={use.isPending && use.variables === x.id}
                  onPress={() => (mine ? onChange(mine.id) : use.mutate(x.id))} />
              );
            })}
          </ScrollView>
          {use.isError ? <Text style={{ color: t.danger }}>{use.error.message}</Text> : null}
        </>
      ) : null}
    </View>
  );
}

function TemplateCard({ x, selected, busy, onPress }: { x: Template; selected: boolean; busy: boolean; onPress: () => void }) {
  return (
    <Frame selected={selected} onPress={onPress} label={`${x.emoji} ${x.name}`} sub={x.tagline}>
      <Image source={{ uri: x.cover_url }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} />
      {busy ? <View style={styles.busy}><ActivityIndicator color="#fff" /></View> : null}
    </Frame>
  );
}

function Frame({ selected, onPress, children, label, sub }: {
  selected: boolean; onPress: () => void; children: React.ReactNode; label: string; sub?: string;
}) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="radio" accessibilityState={{ selected }} style={{ width: CARD_W, gap: Spacing.one }}>
      <View style={[styles.card, { borderColor: selected ? t.accent : t.border, backgroundColor: t.backgroundElement }]}>
        {children}
        {selected ? (
          <View style={[styles.tick, { backgroundColor: t.accent }]}>
            <Text style={{ color: t.onAccent, fontWeight: '800' }}>✓</Text>
          </View>
        ) : null}
      </View>
      <Text style={{ color: selected ? t.accent : t.text, fontWeight: '700' }} numberOfLines={1}>{label}</Text>
      {sub ? <Text style={{ color: t.textSecondary, fontSize: 12 }} numberOfLines={2}>{sub}</Text> : null}
    </Pressable>
  );
}

function StyleCard({ s, selected, onPress }: { s: Style; selected: boolean; onPress: () => void }) {
  const t = useTheme();
  const refs = useQuery({ queryKey: ['references', s.id], queryFn: () => api.references(s.id), staleTime: 5 * 60_000 });
  const sheet = refs.data?.find((r) => r.contact_sheet_url)?.contact_sheet_url;
  const accent = s.profile?.look?.accent_color ?? t.accent;
  return (
    <Frame selected={selected} onPress={onPress} label={s.profile?.name ?? s.name} sub={s.profile?.pacing?.reel_type ?? s.profile?.hook?.style}>
      {sheet ? <Image source={{ uri: sheet }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} /> : null}
      <View style={[styles.badge, { backgroundColor: accent }]} />
    </Frame>
  );
}

function PlainCard({ selected, onPress }: { selected: boolean; onPress: () => void }) {
  const t = useTheme();
  return (
    <Frame selected={selected} onPress={onPress} label="Clean" sub="Simple cuts and captions">
      <View style={styles.center}>
        <Text style={{ fontSize: 40 }}>✂️</Text>
        <View style={[styles.fakeCap, { backgroundColor: t.text }]} />
      </View>
    </Frame>
  );
}

function LearnCard() {
  const t = useTheme();
  return (
    <Pressable onPress={() => router.push('/styles/new')} style={{ width: CARD_W, gap: Spacing.one }}>
      <View style={[styles.card, styles.center, { borderColor: t.border, borderStyle: 'dashed' }]}>
        <Text style={{ color: t.accent, fontSize: 36 }}>＋</Text>
        <Text style={{ color: t.textSecondary, fontSize: 13, textAlign: 'center', paddingHorizontal: Spacing.two }}>Paste reels you love</Text>
      </View>
      <Text style={{ color: t.text, fontWeight: '700' }}>Learn a look</Text>
      <Text style={{ color: t.textSecondary, fontSize: 12 }}>Learns the editing, never the content</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { gap: Spacing.three, paddingVertical: Spacing.one },
  card: { width: CARD_W, aspectRatio: 9 / 16, borderRadius: Radius.lg, borderWidth: 2, overflow: 'hidden' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: Spacing.two },
  tick: { position: 'absolute', right: 8, bottom: 8, width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  badge: { position: 'absolute', left: 8, top: 8, width: 14, height: 14, borderRadius: 7, borderWidth: 2, borderColor: '#fff' },
  fakeCap: { width: 80, height: 8, borderRadius: 4, opacity: 0.7 },
  busy: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.4)', alignItems: 'center', justifyContent: 'center' },
});
