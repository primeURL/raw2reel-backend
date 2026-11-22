/** New reel: the brief (title, style, language, script, stats). Clips are added on the next screen. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';

import { Button, Choice, Field, SectionTitle } from '@/components/ui';
import { VoiceButton } from '@/components/voice-button';
import { MaxContentWidth, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { Language } from '@/lib/types';

const LANGUAGES: { value: Language; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'hinglish', label: 'Hinglish' },
];

export default function NewReelScreen() {
  const t = useTheme();
  const qc = useQueryClient();
  const styles_ = useQuery({ queryKey: ['styles'], queryFn: api.styles });
  const readyStyles = (styles_.data ?? []).filter((s) => s.status === 'ready');

  const [title, setTitle] = useState('');
  const [styleId, setStyleId] = useState<string | null | undefined>(undefined); // undefined = default to first ready style
  const [language, setLanguage] = useState<Language>('en');
  const [script, setScript] = useState('');
  const [stats, setStats] = useState<{ label: string; value: string }[]>([
    { label: 'Distance', value: '' },
    { label: 'Pace', value: '' },
    { label: 'Time', value: '' },
  ]);
  const chosenStyle = styleId === undefined ? (readyStyles[0]?.id ?? null) : styleId;

  const create = useMutation({
    mutationFn: () => {
      const filled = Object.fromEntries(stats.filter((s) => s.label.trim() && s.value.trim()).map((s) => [s.label.trim(), s.value.trim()]));
      return api.createProject({
        title: title.trim() || 'Untitled reel',
        style_id: chosenStyle,
        language,
        script: script.trim() || null,
        stats: Object.keys(filled).length ? filled : null,
      });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] });
      router.replace({ pathname: '/reel/[id]', params: { id: p.id } });
    },
  });

  const setStat = (i: number, key: 'label' | 'value', v: string) =>
    setStats((rows) => rows.map((r, j) => (j === i ? { ...r, [key]: v } : r)));

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
          <Field label="Title" value={title} onChangeText={setTitle} placeholder="e.g. Day 2 - 3 km" maxLength={200} />

          <SectionTitle>Style</SectionTitle>
          <View style={styles.choices}>
            {readyStyles.map((s) => (
              <Choice key={s.id} label={s.profile?.name ?? s.name} selected={chosenStyle === s.id} onPress={() => setStyleId(s.id)} />
            ))}
            <Choice label="No style" selected={chosenStyle === null} onPress={() => setStyleId(null)} />
          </View>
          {!styles_.isPending && readyStyles.length === 0 ? (
            <Text style={[styles.hint, { color: t.textSecondary }]}>No ready style yet - the edit will be clean and simple. You can make one in Styles.</Text>
          ) : null}

          <SectionTitle>Language you speak or write in</SectionTitle>
          <View style={styles.choices}>
            {LANGUAGES.map((l) => (
              <Choice key={l.value} label={l.label} selected={language === l.value} onPress={() => setLanguage(l.value)} />
            ))}
          </View>

          <Field
            label="Script or story (optional)"
            value={script}
            onChangeText={setScript}
            multiline
            maxLength={4000}
            placeholder={'The order of your clips and the lines to show, e.g.\nDay 2. Warm-up first. Target 3 km. Done!'}
          />
          <VoiceButton language={language} label="Speak your script" onText={(x) => setScript((s) => (s.trim() ? `${s.trim()}\n${x}` : x))} />

          <SectionTitle>Stats for the end card (optional)</SectionTitle>
          <Text style={[styles.hint, { color: t.textSecondary }]}>Only what you fill in is shown - Raw2Reel never invents numbers.</Text>
          {stats.map((s, i) => (
            <View key={i} style={styles.statRow}>
              <View style={{ flex: 1 }}>
                <Field value={s.label} onChangeText={(v) => setStat(i, 'label', v)} placeholder="Label" maxLength={40} />
              </View>
              <View style={{ flex: 1.3 }}>
                <Field value={s.value} onChangeText={(v) => setStat(i, 'value', v)} placeholder={['2.06 km', '7\'20" /km', '15:10'][i] ?? 'Value'} maxLength={40} />
              </View>
            </View>
          ))}

          {create.isError ? <Text style={{ color: t.danger }}>{create.error.message}</Text> : null}
          <Button label="Next: add clips" onPress={() => create.mutate()} loading={create.isPending} />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingBottom: Spacing.six, alignItems: 'center' },
  wrap: { width: '100%', maxWidth: MaxContentWidth, padding: Spacing.four, gap: Spacing.three },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  hint: { fontSize: 14 },
  statRow: { flexDirection: 'row', gap: Spacing.two },
});
