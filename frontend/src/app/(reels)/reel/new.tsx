/**
 * New reel, clips first: 1. pick your clips  2. pick a look  3. go.
 * Title, language, script and stats are optional and folded away under "More options".
 * Uploads start right away and keep going on the reel screen (lib/uploads.ts).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ChoicesSheet, prefsSummary } from '@/components/choices';
import { LookPicker } from '@/components/look-picker';
import { Button, Choice, Field, SectionTitle, formatSeconds } from '@/components/ui';
import { VoiceButton } from '@/components/voice-button';
import { MaxContentWidth, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { Language, Prefs } from '@/lib/types';
import { MAX_CLIPS, type PickedClip, pickClips, uploadClips } from '@/lib/uploads';

const LANGUAGES: { value: Language; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'hinglish', label: 'Hinglish' },
];

const defaultTitle = () => `Reel · ${new Date().toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}`;

export default function NewReelScreen() {
  const t = useTheme();
  const qc = useQueryClient();
  const styles_ = useQuery({ queryKey: ['styles'], queryFn: api.styles });
  const readyStyles = (styles_.data ?? []).filter((s) => s.status === 'ready');

  const [clips, setClips] = useState<PickedClip[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [styleId, setStyleId] = useState<string | null | undefined>(undefined); // undefined = first ready style
  const [more, setMore] = useState(false);
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [title, setTitle] = useState('');
  const [language, setLanguage] = useState<Language>('en');
  const [script, setScript] = useState('');
  const chosenStyle = styleId === undefined ? (readyStyles[0]?.id ?? null) : styleId;
  const seconds = clips.reduce((s, c) => s + (c.duration ?? 0) / 1000, 0);

  async function pick() {
    const res = await pickClips(MAX_CLIPS - clips.length);
    setNote(res.note);
    if (res.clips.length) setClips((c) => [...c, ...res.clips]);
  }

  const create = useMutation({
    mutationFn: () => api.createProject({
      title: title.trim() || defaultTitle(),
      style_id: chosenStyle,
      language,
      script: script.trim() || null,
      prefs,
    }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] });
      if (clips.length) uploadClips(p.id, clips, () => qc.invalidateQueries({ queryKey: ['project', p.id] }));
      router.replace({ pathname: '/reel/[id]', params: { id: p.id } });
    },
  });

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: t.background }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Stack.Screen
        options={{
          headerLeft: () => (
            <Button label="Cancel" kind="ghost" style={{ minHeight: 36, paddingHorizontal: Spacing.three }}
              onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />
          ),
        }}
      />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.wrap}>
          <Step n={1} title="Add your raw clips" done={clips.length > 0} />
          {clips.length ? (
            <View style={[styles.picked, { backgroundColor: t.backgroundElement, borderColor: t.border }]}>
              {clips.map((c, i) => (
                <View key={`${c.uri}-${i}`} style={styles.pickedRow}>
                  <Text style={[styles.alias, { color: t.accent }]}>C{i + 1}</Text>
                  <Text style={{ color: t.text, flex: 1 }} numberOfLines={1}>{c.fileName ?? `Clip ${i + 1}`}</Text>
                  <Text style={{ color: t.textSecondary }}>{formatSeconds((c.duration ?? 0) / 1000)}</Text>
                  <Pressable hitSlop={10} onPress={() => setClips((x) => x.filter((_, j) => j !== i))} accessibilityLabel="Remove clip">
                    <Text style={{ color: t.textSecondary, fontSize: 18 }}>×</Text>
                  </Pressable>
                </View>
              ))}
              <Text style={{ color: t.textSecondary, fontSize: 13 }}>{clips.length} clip{clips.length === 1 ? '' : 's'} · {formatSeconds(seconds)} · in this order</Text>
              {clips.length < MAX_CLIPS ? <Button label="+ Add more" kind="ghost" style={styles.small} onPress={pick} /> : null}
            </View>
          ) : (
            <Pressable onPress={pick} style={[styles.drop, { borderColor: t.accent, backgroundColor: t.accent + '14' }]}>
              <Text style={{ fontSize: 40 }}>🎬</Text>
              <Text style={{ color: t.text, fontSize: 18, fontWeight: '700' }}>Pick clips from your phone</Text>
              <Text style={{ color: t.textSecondary, textAlign: 'center' }}>Tap them in the order you want. Up to {MAX_CLIPS}, 5 min each.</Text>
            </Pressable>
          )}
          {note ? <Text style={{ color: t.danger }}>{note}</Text> : null}

          <Step n={2} title="Pick a look" done />
          <LookPicker value={chosenStyle} onChange={setStyleId} />

          <Step n={3} title="Captions & sounds" done />
          <Pressable onPress={() => setChoosing(true)} style={[styles.choose, { borderColor: t.accent, backgroundColor: t.accent + '12' }]}>
            <Text style={{ fontSize: 26 }}>💬</Text>
            <View style={{ flex: 1 }}>
              <Text style={{ color: t.text, fontWeight: '700' }}>{prefsSummary(prefs)}</Text>
              <Text style={{ color: t.textSecondary, fontSize: 13 }}>Pop, typewriter or slide-up captions, sound effects, transitions… see them before you start.</Text>
            </View>
            <Text style={{ color: t.accent, fontWeight: '700' }}>Choose ›</Text>
          </Pressable>
          <ChoicesSheet open={choosing} value={prefs} onClose={() => setChoosing(false)}
            onSave={(p) => { setPrefs(p); setChoosing(false); }} />

          <Pressable onPress={() => setMore((m) => !m)} style={[styles.more, { borderColor: t.border }]}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: t.text, fontWeight: '600' }}>More options</Text>
              <Text style={{ color: t.textSecondary, fontSize: 13 }}>Title, captions language, your story</Text>
            </View>
            <Text style={{ color: t.textSecondary, fontSize: 18 }}>{more ? '▴' : '▾'}</Text>
          </Pressable>
          {more ? (
            <View style={{ gap: Spacing.three }}>
              <Field label="Title" value={title} onChangeText={setTitle} placeholder={defaultTitle()} maxLength={200} />
              <SectionTitle>Captions language</SectionTitle>
              <View style={styles.choices}>
                {LANGUAGES.map((l) => <Choice key={l.value} label={l.label} selected={language === l.value} onPress={() => setLanguage(l.value)} />)}
              </View>
              <Field label="Your story (optional)" value={script} onChangeText={setScript} multiline maxLength={4000}
                placeholder={'What happens, in your words, e.g.\nDay 2. Warm-up first. Target 3 km. Done!'} />
              <VoiceButton language={language} label="Say it instead" onText={(x) => setScript((s) => (s.trim() ? `${s.trim()}\n${x}` : x))} />
            </View>
          ) : null}

          {create.isError ? <Text style={{ color: t.danger }}>{create.error.message}</Text> : null}
          <Button label={clips.length ? 'Create reel' : 'Pick clips first'} disabled={!clips.length} onPress={() => create.mutate()} loading={create.isPending} />
          <Text style={{ color: t.textSecondary, fontSize: 13, textAlign: 'center' }}>Your clips upload while you carry on. Nothing is edited until you say so.</Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Step({ n, title, done }: { n: number; title: string; done?: boolean }) {
  const t = useTheme();
  return (
    <View style={styles.step}>
      <View style={[styles.stepDot, { backgroundColor: done ? t.accent : t.backgroundSelected }]}>
        <Text style={{ color: done ? t.onAccent : t.textSecondary, fontWeight: '800', fontSize: 13 }}>{n}</Text>
      </View>
      <Text style={{ color: t.text, fontSize: 20, fontWeight: '700' }}>{title}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingBottom: Spacing.six, alignItems: 'center' },
  wrap: { width: '100%', maxWidth: MaxContentWidth, padding: Spacing.four, gap: Spacing.three },
  step: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, marginTop: Spacing.two },
  stepDot: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  drop: { borderWidth: 2, borderStyle: 'dashed', borderRadius: Radius.lg, padding: Spacing.five, alignItems: 'center', gap: Spacing.two },
  picked: { borderWidth: StyleSheet.hairlineWidth, borderRadius: Radius.lg, padding: Spacing.three, gap: Spacing.two },
  pickedRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  alias: { width: 28, fontWeight: '800', fontSize: 13 },
  small: { minHeight: 36, alignSelf: 'flex-start', paddingHorizontal: 0 },
  choose: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, borderWidth: 1.5, borderRadius: Radius.lg, padding: Spacing.three },
  more: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: Radius.md, padding: Spacing.three, marginTop: Spacing.two },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
});
