/**
 * One style, start to finish:
 *   add reference reels (Instagram link or video from the phone)
 *   -> learn the style (1 AI call, confirmed first)
 *   -> answer 3 questions (1 AI call) or skip
 *   -> ready: show what was learned
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, Choice, Field, Loading, Message, Screen, SectionTitle, StatusChip, formatSeconds } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { uploadToStorage } from '@/lib/upload';
import type { Reference, Style } from '@/lib/types';

const MAX_REFS = 6;
const MAX_REF_SECONDS = 180;
const BUSY = new Set(['pending', 'downloading', 'processing']);
const refBusy = (r: Reference) => BUSY.has(r.status) || (r.status === 'ready' && (!r.analysis_status || BUSY.has(r.analysis_status)));

export default function StyleDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const style = useQuery({
    queryKey: ['style', id],
    queryFn: () => api.style(id),
    refetchInterval: (q) => (q.state.data?.status === 'analyzing' ? 3000 : false),
  });
  const refs = useQuery({
    queryKey: ['references', id],
    queryFn: () => api.references(id),
    refetchInterval: (q) => (q.state.data?.some(refBusy) ? 3000 : false),
  });

  if (style.isPending) return <Loading />;
  if (style.isError) return <Message title="Couldn't load this style" body={style.error.message} />;
  const s = style.data;

  return (
    <>
      <Stack.Screen options={{ title: s.profile?.name ?? s.name }} />
      <Screen title={s.profile?.name ?? s.name} right={<StatusChip status={s.status} />} onRefresh={() => Promise.all([style.refetch(), refs.refetch()])}>
        {s.status === 'needs_answers' ? <Questions s={s} /> : null}
        {s.status === 'ready' && s.profile ? <Learned s={s} /> : null}
        {s.status === 'analyzing' ? <Working /> : null}
        <References styleId={id} s={s} refs={refs.data ?? []} loading={refs.isPending} />
        {s.status === 'draft' || s.status === 'failed' || s.status === 'ready' ? <Learn s={s} refs={refs.data ?? []} /> : null}
        <DeleteStyle id={id} />
      </Screen>
    </>
  );
}

function Working() {
  const t = useTheme();
  return (
    <Card>
      <Text style={{ fontSize: 16, fontWeight: '600', color: t.text }}>Learning your style…</Text>
      <Text style={{ color: t.textSecondary }}>Watching your reference reels. This takes about half a minute.</Text>
    </Card>
  );
}

// references ------------------------------------------------------------------

function References({ styleId, s, refs, loading }: { styleId: string; s: Style; refs: Reference[]; loading: boolean }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [link, setLink] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const full = refs.length >= MAX_REFS;
  const locked = s.status === 'analyzing';
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['references', styleId] });
    qc.invalidateQueries({ queryKey: ['style', styleId] });
    qc.invalidateQueries({ queryKey: ['styles'] });
  };

  const addLink = useMutation({
    mutationFn: () => api.importInstagram(link.trim(), styleId),
    onSuccess: () => {
      setLink('');
      setError(null);
      refresh();
    },
    onError: (e) => setError(e.message),
  });

  async function pickVideo() {
    setError(null);
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      setError('Allow access to your videos to upload a reference.');
      return;
    }
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['videos'], allowsEditing: false, allowsMultipleSelection: false });
    if (res.canceled || !res.assets?.length) return;
    const a = res.assets[0];
    if (a.duration && a.duration / 1000 > MAX_REF_SECONDS) {
      setError('That video is longer than 3 minutes - pick a shorter reel.');
      return;
    }
    setUploading(true);
    try {
      const ticket = await api.referenceUploadUrl(a.fileName ?? 'reference.mp4', a.mimeType ?? 'video/mp4');
      await uploadToStorage(a.uri, ticket.upload_url, ticket.headers);
      await api.completeReference(ticket.reference_id, styleId);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  return (
    <>
      <SectionTitle>
        Reference reels · {refs.length}/{MAX_REFS}
      </SectionTitle>
      {loading ? <Loading /> : refs.map((r) => <ReferenceRow key={r.id} r={r} styleId={styleId} disabled={locked} />)}
      {refs.length === 0 && !loading ? (
        <Text style={{ color: t.textSecondary, fontSize: 15 }}>Add 3-4 reels whose editing you love. Different reels with a shared feel work best.</Text>
      ) : null}
      {!full && !locked ? (
        <Card>
          <Field
            label="Instagram reel link"
            value={link}
            onChangeText={setLink}
            placeholder="https://www.instagram.com/reel/…"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            onSubmitEditing={() => link.trim() && addLink.mutate()}
          />
          <View style={styles.row}>
            <Button label="Add link" onPress={() => addLink.mutate()} loading={addLink.isPending} disabled={!link.trim()} style={{ flex: 1 }} />
            <Button label={uploading ? 'Uploading…' : 'Upload video'} kind="secondary" onPress={pickVideo} loading={uploading} style={{ flex: 1 }} />
          </View>
          {error ? <Text style={{ color: t.danger }}>{error}</Text> : null}
        </Card>
      ) : null}
    </>
  );
}

function ReferenceRow({ r, styleId, disabled }: { r: Reference; styleId: string; disabled: boolean }) {
  const t = useTheme();
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.deleteReference(r.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['references', styleId] });
      qc.invalidateQueries({ queryKey: ['style', styleId] });
    },
  });
  const retry = useMutation({
    mutationFn: () => api.retryReference(r.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['references', styleId] }),
  });

  const label =
    r.status === 'failed' ? 'Failed' :
    r.status === 'downloading' ? 'Downloading from Instagram…' :
    r.status !== 'ready' ? 'Processing…' :
    r.analysis_status === 'ready' ? `${formatSeconds(r.duration_s ?? 0)} · ${r.pacing?.shot_count ?? '?'} shot${r.pacing?.shot_count === 1 ? '' : 's'}` :
    r.analysis_status === 'failed' ? 'Analysis failed' : 'Watching the reel…';

  return (
    <Card style={styles.refRow}>
      <View style={[styles.sheet, { backgroundColor: t.backgroundSelected }]}>
        {r.contact_sheet_url ? <Image source={{ uri: r.contact_sheet_url }} style={StyleSheet.absoluteFill} contentFit="cover" contentPosition="left" /> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ color: t.text, fontWeight: '600' }} numberOfLines={1}>
          {r.source === 'instagram' ? `Instagram · ${r.shortcode}` : 'Uploaded video'}
        </Text>
        <Text style={{ color: r.status === 'failed' ? t.danger : t.textSecondary, fontSize: 13 }} numberOfLines={3}>
          {r.status === 'failed' && r.error ? r.error : label}
        </Text>
        {r.transcript_text ? (
          <Text style={{ color: t.textSecondary, fontSize: 12, fontStyle: 'italic' }} numberOfLines={1}>
            “{r.transcript_text}”
          </Text>
        ) : null}
      </View>
      {!disabled ? (
        <View style={{ gap: Spacing.one }}>
          {r.status === 'failed' && r.source === 'instagram' ? <Button label="Retry" kind="ghost" onPress={() => retry.mutate()} loading={retry.isPending} style={styles.small} /> : null}
          <Button label="Remove" kind="ghost" onPress={() => del.mutate()} loading={del.isPending} style={styles.small} />
        </View>
      ) : null}
    </Card>
  );
}

// learn -------------------------------------------------------------------------

function Learn({ s, refs }: { s: Style; refs: Reference[] }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const usage = useQuery({ queryKey: ['ai-usage'], queryFn: api.aiUsage, enabled: confirming });
  const ready = refs.filter((r) => r.analysis_status === 'ready').length;
  const busy = refs.some(refBusy);
  const analyze = useMutation({
    mutationFn: () => api.analyzeStyle(s.id),
    onSuccess: () => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ['style', s.id] });
      qc.invalidateQueries({ queryKey: ['styles'] });
      qc.invalidateQueries({ queryKey: ['ai-usage'] });
    },
  });

  const cta = s.status === 'ready' ? 'Re-learn from these reels' : 'Learn my style';
  const hint = busy
    ? 'Waiting for your reels to finish processing…'
    : ready === 0
      ? 'Add at least one reel to start.'
      : ready < 3
        ? `${ready} reel${ready === 1 ? '' : 's'} ready - 3-4 give a better style, but you can start now.`
        : `${ready} reels ready.`;

  if (!confirming) {
    return (
      <View style={{ gap: Spacing.two, marginTop: Spacing.two }}>
        {s.status === 'failed' && s.error ? <Text style={{ color: t.danger }}>{s.error}</Text> : null}
        <Text style={{ color: t.textSecondary, fontSize: 14 }}>{hint}</Text>
        <Button label={cta} kind={s.status === 'ready' ? 'secondary' : 'primary'} onPress={() => setConfirming(true)} disabled={busy || ready === 0} />
      </View>
    );
  }
  const left = usage.data ? usage.data.daily_limit - usage.data.calls_last_24h : null;
  return (
    <Card style={{ borderColor: t.accent }}>
      <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }}>Learn the style from {ready} reel{ready === 1 ? '' : 's'}?</Text>
      <Text style={{ color: t.textSecondary }}>
        This uses 1 AI edit{left !== null ? ` (${left} of ${usage.data!.daily_limit} left today)` : ''}.
        {s.status === 'ready' ? ' Your current style and answers will be replaced.' : ''}
      </Text>
      {analyze.isError ? <Text style={{ color: t.danger }}>{analyze.error.message}</Text> : null}
      <View style={styles.row}>
        <Button label="Cancel" kind="secondary" onPress={() => setConfirming(false)} style={{ flex: 1 }} />
        <Button label="Learn it" onPress={() => analyze.mutate()} loading={analyze.isPending} disabled={left === 0} style={{ flex: 1 }} />
      </View>
    </Card>
  );
}

// questions -----------------------------------------------------------------------

function Questions({ s }: { s: Style }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState('');
  const done = () => {
    qc.invalidateQueries({ queryKey: ['style', s.id] });
    qc.invalidateQueries({ queryKey: ['styles'] });
    qc.invalidateQueries({ queryKey: ['ai-usage'] });
  };
  const send = useMutation({
    mutationFn: () => api.answerStyle(s.id, Object.entries(picked).map(([question_id, answer]) => ({ question_id, answer })), notes.trim()),
    onSuccess: done,
  });
  const skip = useMutation({ mutationFn: () => api.skipQuestions(s.id), onSuccess: done });
  const canSend = Object.keys(picked).length > 0 || notes.trim().length > 0;

  return (
    <>
      {s.profile ? (
        <Card>
          <Text style={{ color: t.text, fontSize: 16, lineHeight: 23 }}>{s.profile.summary}</Text>
        </Card>
      ) : null}
      <SectionTitle>3 quick questions</SectionTitle>
      {(s.questions ?? []).map((q) => (
        <Card key={q.id}>
          <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }}>{q.question}</Text>
          <Text style={{ color: t.textSecondary, fontSize: 13 }}>{q.why}</Text>
          <View style={styles.choices}>
            {q.options.map((o) => (
              <Choice key={o} label={o} selected={picked[q.id] === o} onPress={() => setPicked((p) => ({ ...p, [q.id]: o }))} />
            ))}
          </View>
        </Card>
      ))}
      <Field label="Anything else? (optional)" value={notes} onChangeText={setNotes} multiline maxLength={1000}
        placeholder="e.g. small calm captions, orange accent, stats card at the end" />
      {send.isError ? <Text style={{ color: t.danger }}>{send.error.message}</Text> : null}
      <Button label="Save answers (1 AI edit)" onPress={() => send.mutate()} loading={send.isPending} disabled={!canSend} />
      <Button label="Skip - use it as it is" kind="ghost" onPress={() => skip.mutate()} loading={skip.isPending} />
    </>
  );
}

// learned -------------------------------------------------------------------------

function Learned({ s }: { s: Style }) {
  const t = useTheme();
  const p = s.profile!;
  const facts: [string, string | undefined][] = [
    ['Reel type', p.pacing?.reel_type?.replace('_', ' ')],
    ['Length', p.pacing?.target_length_s ? `${p.pacing.target_length_s[0]}-${p.pacing.target_length_s[1]} s` : undefined],
    ['Shots', p.pacing?.shot_length_s ? `${p.pacing.shot_length_s[0]}-${p.pacing.shot_length_s[1]} s each` : undefined],
    ['Captions', [p.captions?.size, p.captions?.mode?.replace('_', ' '), p.captions?.position?.replace('_', ' ')].filter(Boolean).join(', ') || undefined],
    ['Look', [p.look?.grade?.replace(/_/g, ' '), p.look?.zooms?.replace(/_/g, ' '), p.look?.transitions?.replace(/_/g, ' ')].filter(Boolean).join(', ') || undefined],
    ['Music', [p.sound?.music?.replace(/_/g, ' '), p.sound?.music_mood].filter(Boolean).join(' - ') || undefined],
    ['Ending', p.ending?.style?.replace(/_/g, ' ')],
  ];
  return (
    <>
      <Card>
        <Text style={{ color: t.text, fontSize: 16, lineHeight: 23 }}>{p.summary}</Text>
        <View style={styles.accentRow}>
          <View style={[styles.swatch, { backgroundColor: p.look?.accent_color ?? t.accent }]} />
          <Text style={{ color: t.textSecondary }}>Accent {p.look?.accent_color}</Text>
        </View>
      </Card>
      <Card>
        {facts.filter(([, v]) => v).map(([k, v]) => (
          <View key={k} style={styles.fact}>
            <Text style={{ color: t.textSecondary, width: 90 }}>{k}</Text>
            <Text style={{ color: t.text, flex: 1 }}>{v}</Text>
          </View>
        ))}
      </Card>
      {p.do?.length ? (
        <Card>
          <Text style={{ color: t.text, fontWeight: '600' }}>Always</Text>
          {p.do.slice(0, 6).map((d) => <Text key={d} style={{ color: t.textSecondary }}>• {d}</Text>)}
        </Card>
      ) : null}
    </>
  );
}

function DeleteStyle({ id }: { id: string }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [sure, setSure] = useState(false);
  const del = useMutation({
    mutationFn: () => api.deleteStyle(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['styles'] });
      if (router.canGoBack()) router.back();
      else router.replace('/styles'); // opened from a link: nothing to go back to
    },
  });
  return (
    <View style={{ marginTop: Spacing.four }}>
      {sure ? (
        <View style={styles.row}>
          <Button label="Keep it" kind="secondary" onPress={() => setSure(false)} style={{ flex: 1 }} />
          <Button label="Delete style" onPress={() => del.mutate()} loading={del.isPending} style={{ flex: 1, backgroundColor: t.danger }} />
        </View>
      ) : (
        <Button label="Delete this style" kind="ghost" onPress={() => setSure(true)} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: Spacing.two },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two, marginTop: Spacing.one },
  refRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, padding: Spacing.two },
  sheet: { width: 64, height: 64, borderRadius: Radius.sm, overflow: 'hidden' },
  small: { minHeight: 32, paddingHorizontal: Spacing.two },
  swatch: { width: 14, height: 14, borderRadius: Radius.pill },
  accentRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  fact: { flexDirection: 'row', gap: Spacing.two, paddingVertical: 2 },
});
