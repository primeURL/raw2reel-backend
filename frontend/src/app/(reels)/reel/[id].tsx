/**
 * One reel, as three steps: Clips -> Edit -> Export.
 * Only the current step is open; the rest is one tap away (clips sheet, editor, export sheet).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useVideoPlayer, VideoView } from 'expo-video';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { ChoicesSheet, prefsSummary } from '@/components/choices';
import { ConfirmAI } from '@/components/confirm-ai';
import { ExportSheet, useRenders } from '@/components/export-sheet';
import { Making } from '@/components/making';
import { Sheet } from '@/components/sheet';
import { VoiceButton } from '@/components/voice-button';
import { Button, Card, Loading, Message, ProgressBar, Screen, formatSeconds } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { saveToGallery, shareVideo } from '@/lib/share';
import { soundCues } from '@/lib/sfx-cues';
import type { Clip, Prefs, Project, Render } from '@/lib/types';
import { type LocalUpload, MAX_CLIPS, dismissUpload, pickClips, uploadClips, useUploads } from '@/lib/uploads';

const BUSY = new Set(['pending', 'downloading', 'processing']);
const clipBusy = (c: Clip) => BUSY.has(c.status) || (c.status === 'ready' && (!c.analysis_status || BUSY.has(c.analysis_status)));

export default function ReelScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const uploads = useUploads(id);
  const q = useQuery({
    queryKey: ['project', id],
    queryFn: () => api.project(id),
    refetchInterval: (query) => {
      const p = query.state.data;
      return p && (p.status === 'analyzing' || p.status === 'rendering' || p.clips.some(clipBusy)) ? 3000 : false;
    },
  });

  if (q.isPending) return <Loading />;
  if (q.isError) return <Message title="Couldn't load this reel" body={q.error.message} />;
  return <Hub p={q.data} uploads={uploads} refetch={q.refetch} />;
}

function Hub({ p, uploads, refetch }: { p: Project; uploads: LocalUpload[]; refetch: () => unknown }) {
  const t = useTheme();
  const [clipsOpen, setClipsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const hasPlan = !!p.plan && p.status !== 'analyzing';
  const step = p.status === 'analyzing' ? 1 : hasPlan ? 2 : 0;
  const uploading = uploads.some((u) => !u.error);

  return (
    <>
      <Stack.Screen options={{ title: '' }} />
      <Screen title={p.title} onRefresh={refetch}>
        <Steps step={step} />
        {step === 0 ? (
          <>
            <ClipList p={p} uploads={uploads} />
            <StartEdit p={p} uploading={uploading} />
          </>
        ) : step === 1 ? (
          <Making since={p.updated_at} title={p.plan ? 'Making your changes' : 'Making your reel'} thumbs={<ClipStrip clips={p.clips} />} />
        ) : (
          <Result p={p} onClips={() => setClipsOpen(true)} onExport={() => setExportOpen(true)} uploading={uploading} />
        )}
        {p.status === 'failed' && p.error ? <Text style={{ color: t.danger }}>{p.error}</Text> : null}
        <MoreActions p={p} />
      </Screen>
      <Sheet open={clipsOpen} onClose={() => setClipsOpen(false)} title={`Clips · ${p.clips.length}`}>
        <ClipList p={p} uploads={uploads} />
      </Sheet>
      <ExportSheet projectId={p.id} title={p.title} open={exportOpen} onClose={() => setExportOpen(false)} />
    </>
  );
}

// step bar ----------------------------------------------------------------------------

function Steps({ step }: { step: number }) {
  const t = useTheme();
  const labels = ['Clips', 'Edit', 'Export'];
  const at = step >= 2 ? 2 : step; // making (1) and plan-ready both sit on "Edit"
  return (
    <View style={styles.steps}>
      {labels.map((l, i) => (
        <View key={l} style={styles.stepItem}>
          <View style={[styles.stepBar, { backgroundColor: i <= at ? t.accent : t.backgroundSelected }]} />
          <Text style={{ color: i === at ? t.accent : i < at ? t.text : t.textSecondary, fontSize: 13, fontWeight: '700' }}>
            {i < at ? '✓ ' : ''}{l}
          </Text>
        </View>
      ))}
    </View>
  );
}

// step 1: clips ---------------------------------------------------------------------

function ClipList({ p, uploads }: { p: Project; uploads: LocalUpload[] }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [note, setNote] = useState<string | null>(null);
  const room = MAX_CLIPS - p.clips.length - uploads.filter((u) => !u.error).length;
  const locked = p.status === 'analyzing' || p.status === 'rendering';
  const refresh = () => qc.invalidateQueries({ queryKey: ['project', p.id] });

  async function add() {
    const res = await pickClips(room);
    setNote(res.note);
    if (res.clips.length) uploadClips(p.id, res.clips, refresh);
  }
  const move = useMutation({ mutationFn: (ids: string[]) => api.reorderClips(p.id, ids), onSuccess: refresh });
  const swap = (i: number, j: number) => {
    const ids = p.clips.map((c) => c.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    move.mutate(ids);
  };

  return (
    <View style={{ gap: Spacing.two }}>
      {p.clips.length === 0 && uploads.length === 0 ? (
        <Pressable onPress={add} style={[styles.drop, { borderColor: t.accent, backgroundColor: t.accent + '14' }]}>
          <Text style={{ fontSize: 36 }}>🎬</Text>
          <Text style={{ color: t.text, fontSize: 17, fontWeight: '700' }}>Add your raw clips</Text>
          <Text style={{ color: t.textSecondary, textAlign: 'center' }}>Tap them in the order you want. Shoot vertical; pauses get trimmed.</Text>
        </Pressable>
      ) : null}
      {p.clips.map((c, i) => (
        <ClipRow key={c.id} c={c} index={i} count={p.clips.length} projectId={p.id} locked={locked || move.isPending}
          onUp={() => swap(i, i - 1)} onDown={() => swap(i, i + 1)} />
      ))}
      {uploads.map((u) => (
        <Card key={u.key} style={styles.clipRow}>
          <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]} />
          <View style={{ flex: 1, gap: Spacing.one }}>
            <Text style={{ color: t.text, fontWeight: '600' }} numberOfLines={1}>{u.name}</Text>
            {u.error ? <Text style={{ color: t.danger, fontSize: 13 }}>{u.error}</Text> : <ProgressBar value={u.progress} label="Uploading" />}
          </View>
          {u.error ? <Button label="Dismiss" kind="ghost" style={styles.small} onPress={() => dismissUpload(u.key)} /> : null}
        </Card>
      ))}
      {note ? <Text style={{ color: t.danger }}>{note}</Text> : null}
      {room > 0 && !locked && (p.clips.length || uploads.length) ? <Button label="+ Add more clips" kind="secondary" onPress={add} /> : null}
    </View>
  );
}

function ClipRow({ c, index, count, projectId, locked, onUp, onDown }: {
  c: Clip; index: number; count: number; projectId: string; locked: boolean; onUp: () => void; onDown: () => void;
}) {
  const t = useTheme();
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.deleteClip(projectId, c.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['project', projectId] }),
  });
  const line =
    c.status === 'failed' ? (c.error ?? 'Failed') :
    c.status === 'pending' ? 'Waiting for the upload…' :
    c.status !== 'ready' ? 'Checking the video…' :
    c.analysis_status === 'failed' ? 'Couldn’t listen to this one' :
    c.analysis_status !== 'ready' ? `${formatSeconds(c.duration_s ?? 0)} · listening…` :
    `${formatSeconds(c.duration_s ?? 0)} · ${c.has_speech ? 'you talk' : 'no talking'}`;

  return (
    <Card style={styles.clipRow}>
      <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]}>
        {c.thumbnail_url ? <Image source={{ uri: c.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
        <Text style={styles.alias}>C{index + 1}</Text>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ color: c.status === 'failed' ? t.danger : t.text, fontWeight: '600' }} numberOfLines={2}>{line}</Text>
        {c.transcript_text ? <Text style={{ color: t.textSecondary, fontSize: 13, fontStyle: 'italic' }} numberOfLines={2}>“{c.transcript_text}”</Text> : null}
        {clipBusy(c) ? <Text style={{ color: t.accent, fontSize: 12 }}>Working…</Text> : null}
      </View>
      {!locked ? (
        <View style={styles.actions}>
          <View style={styles.arrows}>
            <Arrow label="↑" disabled={index === 0} onPress={onUp} />
            <Arrow label="↓" disabled={index === count - 1} onPress={onDown} />
          </View>
          <Button label="Remove" kind="ghost" style={styles.small} onPress={() => del.mutate()} loading={del.isPending} />
        </View>
      ) : null}
    </Card>
  );
}

function Arrow({ label, disabled, onPress }: { label: string; disabled: boolean; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable accessibilityLabel={label === '↑' ? 'Move up' : 'Move down'} disabled={disabled} onPress={onPress}
      style={[styles.arrow, { borderColor: t.border, opacity: disabled ? 0.3 : 1 }]}>
      <Text style={{ color: t.text, fontSize: 16 }}>{label}</Text>
    </Pressable>
  );
}

function ClipStrip({ clips }: { clips: Clip[] }) {
  const t = useTheme();
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, flexShrink: 1 }} contentContainerStyle={{ gap: Spacing.one }}>
      {clips.map((c) => (
        <View key={c.id} style={[styles.mini, { backgroundColor: t.backgroundSelected }]}>
          {c.thumbnail_url ? <Image source={{ uri: c.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
        </View>
      ))}
    </ScrollView>
  );
}

function StartEdit({ p, uploading }: { p: Project; uploading: boolean }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const gen = useMutation({
    mutationFn: () => api.generatePlan(p.id),
    onSuccess: () => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ['project', p.id] });
      qc.invalidateQueries({ queryKey: ['projects'] });
      qc.invalidateQueries({ queryKey: ['ai-usage'] });
    },
  });
  const busy = p.clips.some(clipBusy) || uploading;
  if (!p.clips.length && !uploading) return null;
  if (confirming) {
    return (
      <ConfirmAI title="Edit this reel?" confirmLabel="Edit it" onConfirm={() => gen.mutate()} onCancel={() => setConfirming(false)}
        loading={gen.isPending} error={gen.isError ? gen.error.message : null} />
    );
  }
  return (
    <View style={{ gap: Spacing.two, marginTop: Spacing.two }}>
      <Button label={busy ? 'Getting your clips ready…' : '✨ Edit my reel'} onPress={() => setConfirming(true)}
        disabled={busy || !p.analysis_ready} />
      <Text style={{ color: t.textSecondary, fontSize: 13, textAlign: 'center' }}>
        {busy ? 'Uploading and listening to your clips. You can add more meanwhile.' : 'Picks your best takes, cuts the pauses, adds captions and effects.'}
      </Text>
    </View>
  );
}

// step 2-3: the video, what was done, and asking for changes ---------------------------------

const IDEAS = ['Make it faster', 'Add more sound effects', 'Put the best moment first', 'Make it shorter', 'Highlight more words', 'Try another version'];

function Result({ p, onClips, onExport, uploading }: { p: Project; onClips: () => void; onExport: () => void; uploading: boolean }) {
  const t = useTheme();
  const renders = useRenders(p.id);
  const [asking, setAsking] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const ready = (renders.data ?? []).filter((r) => r.status === 'ready' && r.video_url);
  const working = renders.data?.find((r) => r.status === 'pending' || r.status === 'processing');
  const newest = ready[0];
  const making = working && (!newest || working.version > newest.version) ? working : undefined;
  // what's on screen: the version the user tapped, else the newest
  const shown = ready.find((r) => r.id === picked) ?? newest;

  return (
    <View style={{ gap: Spacing.three }}>
      <Hero p={p} latest={shown} making={picked ? undefined : making} onExport={onExport} />
      {shown && (picked || !making) ? <SaveShare r={shown} title={p.title} onFinal={onExport} /> : null}
      {ready.length > 1 || (making && newest) ? (
        <Versions ready={ready} making={making} shownId={picked && shown ? shown.id : making ? null : shown?.id ?? null}
          onPick={(id) => setPicked(id)} onMaking={() => setPicked(null)} />
      ) : null}

      {p.plan_request && p.plan_changes?.length ? (
        <Card>
          <Text style={{ color: t.textSecondary, fontSize: 13 }}>You asked: “{p.plan_request}”</Text>
          {p.plan_changes.map((c) => (
            <Text key={c} style={{ color: t.text }}><Text style={{ color: t.success, fontWeight: '800' }}>✓ </Text>{c}</Text>
          ))}
        </Card>
      ) : null}
      <Remembered p={p} />

      <Button label="✨ Change something" onPress={() => setAsking(true)} />
      <View style={styles.row}>
        <Button label="Export final" kind="secondary" style={{ flex: 1 }} onPress={onExport} />
        <Button label="Fine-tune" kind="secondary" style={{ flex: 1 }} onPress={() => router.push({ pathname: '/reel/plan/[id]', params: { id: p.id } })} />
      </View>

      <Choices p={p} />
      <WhatIDid p={p} />

      <Pressable onPress={onClips} style={[styles.linkRow, { borderColor: t.border }]}>
        <ClipStrip clips={p.clips} />
        <Text style={{ color: t.accent, fontWeight: '600' }}>{uploading ? 'Uploading…' : `Clips · ${p.clips.length}`} ›</Text>
      </Pressable>
      <ChangeSheet p={p} open={asking} onClose={() => setAsking(false)} />
    </View>
  );
}

/** Captions & sounds for this reel: change them, then remake the video. Caption looks need no AI. */
function Choices({ p }: { p: Project }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['project', p.id] });
    qc.invalidateQueries({ queryKey: ['renders', p.id] });
    qc.invalidateQueries({ queryKey: ['projects'] });
  };
  const save = useMutation({
    mutationFn: (prefs: Prefs) => api.updateProject(p.id, { prefs }),
    onSuccess: (proj) => { qc.setQueryData(['project', p.id], proj); setOpen(false); setSaved(true); },
  });
  const remake = useMutation({ mutationFn: () => api.render(p.id, 'preview'), onSuccess: () => { setSaved(false); refresh(); } });
  const redo = useMutation({
    mutationFn: () => api.revise(p.id, 'Apply my updated choices for captions, sound effects, transitions and effects. Keep the story as it is.'),
    onSuccess: () => { setSaved(false); refresh(); qc.invalidateQueries({ queryKey: ['ai-usage'] }); },
  });
  return (
    <>
      <Pressable onPress={() => setOpen(true)} style={[styles.linkRow, { borderColor: t.border }]}>
        <Text style={{ fontSize: 22 }}>💬</Text>
        <View style={{ flex: 1 }}>
          <Text style={{ color: t.text, fontWeight: '700' }}>Captions & sounds</Text>
          <Text style={{ color: t.textSecondary, fontSize: 13 }} numberOfLines={2}>{prefsSummary(p.prefs)}</Text>
        </View>
        <Text style={{ color: t.accent, fontWeight: '700' }}>Change ›</Text>
      </Pressable>
      {saved ? (
        <Card style={{ borderColor: t.accent }}>
          <Text style={{ color: t.text, fontWeight: '700' }}>Saved. Make the video again with these?</Text>
          <Text style={{ color: t.textSecondary, fontSize: 13 }}>Caption looks, sounds on/off and clean cuts apply right away, free. New transitions, more effects or highlights need the AI.</Text>
          <View style={styles.row}>
            <Button label="Remake (free)" kind="secondary" style={{ flex: 1 }} loading={remake.isPending} onPress={() => remake.mutate()} />
            <Button label="✨ AI redo" style={{ flex: 1 }} loading={redo.isPending} onPress={() => redo.mutate()} />
          </View>
          {remake.isError || redo.isError ? <Text style={{ color: t.danger }}>{(remake.error ?? redo.error)?.message}</Text> : null}
          <Text style={{ color: t.textSecondary, fontSize: 12 }}>AI redo uses 1 AI edit.</Text>
        </Card>
      ) : null}
      <ChoicesSheet open={open} value={p.prefs} onClose={() => setOpen(false)} saving={save.isPending}
        background={p.clips[0]?.thumbnail_url} onSave={(prefs) => save.mutate(prefs)} />
    </>
  );
}

/** Save and Share for the video on screen - always right under it. */
function SaveShare({ r, title, onFinal }: { r: Render; title: string; onFinal: () => void }) {
  const t = useTheme();
  const [note, setNote] = useState<string | null>(null);
  const fileName = `${title.replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase() || 'reel'}-v${r.version}.mp4`;
  const save = useMutation({ mutationFn: () => saveToGallery(r.video_url!, fileName), onSuccess: setNote, onError: (e) => setNote(e.message) });
  const share = useMutation({ mutationFn: () => shareVideo(r.video_url!, fileName), onSuccess: setNote, onError: (e) => setNote(e.message) });
  return (
    <View style={{ gap: Spacing.two }}>
      <View style={styles.row}>
        <Button label="⬇ Save" kind="secondary" style={{ flex: 1 }} loading={save.isPending} onPress={() => { setNote(null); save.mutate(); }} />
        <Button label="↗ Share" style={{ flex: 1 }} loading={share.isPending} onPress={() => { setNote(null); share.mutate(); }} />
      </View>
      {r.quality === 'preview' ? (
        <Pressable onPress={onFinal}>
          <Text style={{ color: t.textSecondary, fontSize: 13, textAlign: 'center' }}>
            This is a quick preview. <Text style={{ color: t.accent, fontWeight: '700' }}>Export the final 1080p</Text> before posting.
          </Text>
        </Pressable>
      ) : null}
      {note ? <Text style={{ color: t.textSecondary, textAlign: 'center' }}>{note}</Text> : null}
    </View>
  );
}

/** Every finished version, newest first; tap one to watch, save or share it. */
function Versions({ ready, making, shownId, onPick, onMaking }: {
  ready: Render[]; making?: Render; shownId: string | null; onPick: (id: string) => void; onMaking: () => void;
}) {
  const t = useTheme();
  return (
    <View style={{ gap: Spacing.one }}>
      <Text style={{ color: t.textSecondary, fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1 }}>Your versions</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: Spacing.two }}>
        {making ? (
          <Pressable onPress={onMaking} style={[styles.version, { borderColor: shownId === null ? t.accent : t.border }]}>
            <View style={[styles.versionThumb, styles.center, { backgroundColor: t.backgroundSelected }]}>
              <Text style={{ color: t.accent, fontWeight: '800' }}>{Math.round((making.progress ?? 0) * 100)}%</Text>
            </View>
            <Text style={{ color: t.text, fontSize: 12, fontWeight: '700' }}>v{making.version} · making</Text>
          </Pressable>
        ) : null}
        {ready.map((r) => (
          <Pressable key={r.id} onPress={() => onPick(r.id)} style={[styles.version, { borderColor: r.id === shownId ? t.accent : t.border }]}>
            <View style={[styles.versionThumb, { backgroundColor: t.backgroundSelected }]}>
              {r.thumbnail_url ? <Image source={{ uri: r.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
              {r.quality === 'final' ? <Text style={[styles.badge, { backgroundColor: t.accent }]}>FINAL</Text> : null}
            </View>
            <Text style={{ color: r.id === shownId ? t.accent : t.text, fontSize: 12, fontWeight: '700' }}>v{r.version} · {r.quality === 'final' ? '1080p' : 'preview'}</Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

/** The newest video, playing right here; or its progress while it's being made. */
function Hero({ p, latest, making, onExport }: { p: Project; latest?: Render; making?: Render; onExport: () => void }) {
  const t = useTheme();
  const cover = latest?.thumbnail_url ?? p.clips[0]?.thumbnail_url;
  if (latest && !making) return <InlinePlayer key={latest.id} r={latest} />;
  return (
    <Pressable onPress={making ? undefined : onExport} style={[styles.hero, { backgroundColor: t.backgroundElement, borderColor: t.border }]}>
      {cover ? <Image source={{ uri: cover }} style={StyleSheet.absoluteFill} contentFit="cover" blurRadius={making ? 12 : 0} /> : null}
      <View style={styles.heroShade} />
      {making ? (
        <View style={{ alignItems: 'center', gap: Spacing.two, width: '80%' }}>
          <Text style={{ color: '#fff', fontSize: 44, fontWeight: '800' }}>{Math.round((making.progress ?? 0) * 100)}%</Text>
          <View style={styles.heroTrack}><View style={[styles.heroFill, { width: `${Math.round((making.progress ?? 0) * 100)}%`, backgroundColor: t.accent }]} /></View>
          <Text style={{ color: '#fff', fontWeight: '600' }}>Making your video</Text>
          <Text style={{ color: 'rgba(255,255,255,0.8)', fontSize: 13 }}>{making.stage ?? 'Starting'}</Text>
        </View>
      ) : (
        <View style={{ alignItems: 'center', gap: Spacing.two }}>
          <View style={styles.play}><Text style={{ color: '#fff', fontSize: 26 }}>⚡</Text></View>
          <Text style={{ color: '#fff', fontWeight: '700' }}>Tap to make the video</Text>
        </View>
      )}
    </Pressable>
  );
}

function InlinePlayer({ r }: { r: Render }) {
  const t = useTheme();
  const player = useVideoPlayer(r.video_url!, (pl) => {
    pl.loop = true;
    pl.play();
  });
  return (
    <View style={{ gap: Spacing.one, alignItems: 'center' }}>
      <View style={[styles.hero, { backgroundColor: '#000', borderColor: t.border }]}>
        <VideoView player={player} style={styles.video} contentFit="contain" nativeControls fullscreenOptions={{ enable: true }} />
      </View>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>Version {r.version} · {r.quality === 'final' ? 'Final 1080p' : 'Preview'} · {formatSeconds(r.duration_s ?? 0)}</Text>
    </View>
  );
}

/** What the editor did, in plain words: the story it followed and what it added. */
/** Creator memory: "I'll remember: ..." after a change request, with Undo; and which earlier
 * lessons were kept in this edit. */
function Remembered({ p }: { p: Project }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [forgotten, setForgotten] = useState<string | null>(null);
  const lesson = p.plan_lesson;
  const forget = useMutation({
    mutationFn: (id: string) => api.forgetLesson(id),
    onSuccess: (_, id) => { setForgotten(id); qc.invalidateQueries({ queryKey: ['lessons'] }); },
  });
  const kept = p.plan_kept_lessons ?? [];
  if (!lesson && !kept.length) return null;
  const gone = lesson && forgotten === lesson.id;
  return (
    <Card style={{ gap: Spacing.two }}>
      {lesson ? (
        <View style={[styles.row, { alignItems: 'center' }]}>
          <Text style={{ flex: 1, color: t.text }}>
            <Text style={{ fontWeight: '800' }}>🧠 {gone ? 'Forgotten. ' : "I'll remember: "}</Text>
            {gone ? 'I won\'t use it next time.' : `“${lesson.text}”${lesson.applies_to !== 'all' ? ` (${lesson.applies_to} reels)` : ''}`}
          </Text>
          {gone ? null : (
            <Pressable onPress={() => forget.mutate(lesson.id)} hitSlop={8} disabled={forget.isPending}>
              <Text style={{ color: t.accent, fontWeight: '700' }}>{forget.isPending ? '…' : 'Undo'}</Text>
            </Pressable>
          )}
        </View>
      ) : null}
      {kept.map((k) => (
        <Text key={k} style={{ color: t.textSecondary, fontSize: 13 }}>🧠 {k}</Text>
      ))}
      <Pressable onPress={() => router.push('/profile')} hitSlop={6}>
        <Text style={{ color: t.textSecondary, fontSize: 12 }}>See everything I've learnt in Profile ›</Text>
      </Pressable>
    </Card>
  );
}

function WhatIDid({ p }: { p: Project }) {
  const t = useTheme();
  const plan = p.plan!;
  const total = p.plan_timeline?.total_s ?? 0;
  const cues = soundCues(plan, total);
  const fx = plan.effects ?? [];
  const transitions = plan.shots.filter((s, i) => i > 0 && (s.transition_in ?? 'cut') !== 'cut');
  const highlighted = plan.captions.filter((c) => c.highlight).length;
  const lib = useQuery({ queryKey: ['music'], queryFn: api.music, staleTime: 5 * 60_000, enabled: !!plan.music.track });
  const song = lib.data?.tracks.find((x) => x.id === plan.music.track)?.title;
  const VOL = { low_under_voice: 'under your voice', medium: 'balanced', music_led: 'music first' } as const;
  const lines = [
    `${plan.captions.length} caption${plan.captions.length === 1 ? '' : 's'}${highlighted ? `, ${highlighted} with a key word highlighted` : ''}`,
    fx.length ? `${fx.length} effect${fx.length === 1 ? '' : 's'}: ${[...new Set(fx.map((e) => EFFECT_NAMES[e.type] ?? e.type))].join(', ')}` : 'No effects (calm style)',
    transitions.length ? `${transitions.length} transition${transitions.length === 1 ? '' : 's'}: ${[...new Set(transitions.map((s) => s.transition_in))].join(', ')}` : 'Clean cuts between clips',
    plan.music.enabled ? `🎵 Music${song ? `: ${song}` : plan.music.mood ? ` (${plan.music.mood})` : ''}, ${VOL[plan.music.volume] ?? 'balanced'}, on the beat` : 'No music',
    cues.length ? `${cues.length} sound effect${cues.length === 1 ? '' : 's'}: ${cues.slice(0, 4).map((c) => `${c.icon} ${c.name} at ${c.at.toFixed(1)}s`).join(', ')}${cues.length > 4 ? '…' : ''}` : 'No sound effects',
  ];
  return (
    <Card>
      <Text style={{ color: t.text, fontSize: 17, fontWeight: '700' }}>What I did · {formatSeconds(total)}</Text>
      {plan.summary ? <Text style={{ color: t.textSecondary }}>{plan.summary}</Text> : null}
      {plan.story?.length ? (
        <View style={{ gap: 4, marginTop: Spacing.one }}>
          <Text style={{ color: t.textSecondary, fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1 }}>The story, in order</Text>
          {plan.story.map((b, i) => (
            <Text key={i} style={{ color: t.text }}>
              <Text style={{ color: t.accent, fontWeight: '800' }}>{i + 1}. </Text>{b.beat}
              <Text style={{ color: t.textSecondary, fontSize: 12 }}>  {b.clips.join(', ')}</Text>
            </Text>
          ))}
        </View>
      ) : null}
      <View style={{ gap: 4, marginTop: Spacing.one }}>
        {lines.map((l) => <Text key={l} style={{ color: t.textSecondary, fontSize: 14 }}>• {l}</Text>)}
      </View>
    </Card>
  );
}

const EFFECT_NAMES: Record<string, string> = {
  punch_in: 'punch in', slow_push: 'slow push', spotlight: 'spotlight', grade: 'colour look', freeze_frame: 'freeze frame',
  flash: 'flash', countdown: 'countdown', backdrop_word: 'word behind you',
};

/** "Change something": say it or type it, the AI revises the edit and a new video follows. */
function ChangeSheet({ p, open, onClose }: { p: Project; open: boolean; onClose: () => void }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [confirming, setConfirming] = useState(false);
  const send = useMutation({
    mutationFn: () => api.revise(p.id, text.trim()),
    onSuccess: (proj) => {
      qc.setQueryData(['project', p.id], proj);
      qc.invalidateQueries({ queryKey: ['projects'] });
      qc.invalidateQueries({ queryKey: ['ai-usage'] });
      setConfirming(false);
      setText('');
      onClose();
    },
  });
  return (
    <Sheet open={open} onClose={onClose} title="What should change?">
      <TextInput value={text} onChangeText={setText} multiline maxLength={600} autoFocus
        placeholder={'e.g. Put the oats first and make it faster.\nAdd a pop on each ingredient.'}
        placeholderTextColor={t.textSecondary}
        style={[styles.ask, { color: t.text, borderColor: t.border, backgroundColor: t.background }]} />
      <VoiceButton language={p.language} label="Say it instead" onText={(x) => setText((s) => (s.trim() ? `${s.trim()} ${x}` : x))} />
      <View style={styles.ideas}>
        {IDEAS.map((idea) => (
          <Pressable key={idea} onPress={() => setText((s) => (s.trim() ? `${s.trim()}. ${idea}` : idea))}
            style={[styles.idea, { borderColor: t.border, backgroundColor: t.background }]}>
            <Text style={{ color: t.text, fontSize: 13 }}>{idea}</Text>
          </Pressable>
        ))}
      </View>
      {confirming ? (
        <ConfirmAI title="Make these changes?" note="A new video is made right after." confirmLabel="Make it"
          onConfirm={() => send.mutate()} onCancel={() => setConfirming(false)} loading={send.isPending}
          error={send.isError ? send.error.message : null} />
      ) : (
        <Button label="Make the changes" disabled={text.trim().length < 2} onPress={() => setConfirming(true)} />
      )}
      <Text style={{ color: t.textSecondary, fontSize: 12, textAlign: 'center' }}>Everything you don’t mention stays as it is.</Text>
    </Sheet>
  );
}

// rarely used: rewrite with AI, delete ---------------------------------------------------

function MoreActions({ p }: { p: Project }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [rewrite, setRewrite] = useState(false);
  const [sure, setSure] = useState(false);
  const gen = useMutation({
    mutationFn: () => api.generatePlan(p.id),
    onSuccess: () => {
      setRewrite(false);
      setOpen(false);
      qc.invalidateQueries({ queryKey: ['project', p.id] });
      qc.invalidateQueries({ queryKey: ['projects'] });
      qc.invalidateQueries({ queryKey: ['ai-usage'] });
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteProject(p.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] });
      if (router.canGoBack()) router.back();
      else router.replace('/');
    },
  });
  if (!open) return <Button label="More…" kind="ghost" style={{ marginTop: Spacing.four }} onPress={() => setOpen(true)} />;
  return (
    <View style={{ gap: Spacing.two, marginTop: Spacing.four }}>
      {p.plan && p.status !== 'analyzing' ? (
        rewrite ? (
          <ConfirmAI title="Start the edit over?" note="Your current edit will be replaced. Uses all your clips." confirmLabel="Start over"
            onConfirm={() => gen.mutate()} onCancel={() => setRewrite(false)} loading={gen.isPending} error={gen.isError ? gen.error.message : null} />
        ) : (
          <Button label="Start the edit over with AI" kind="secondary" onPress={() => setRewrite(true)} />
        )
      ) : null}
      {sure ? (
        <View style={styles.row}>
          <Button label="Keep it" kind="secondary" onPress={() => setSure(false)} style={{ flex: 1 }} />
          <Button label="Delete reel" onPress={() => del.mutate()} loading={del.isPending} style={{ flex: 1, backgroundColor: t.danger }} />
        </View>
      ) : (
        <Button label="Delete this reel" kind="ghost" onPress={() => setSure(true)} />
      )}
      <Button label="Close" kind="ghost" onPress={() => setOpen(false)} />
    </View>
  );
}

const styles = StyleSheet.create({
  steps: { flexDirection: 'row', gap: Spacing.two, marginTop: -Spacing.two },
  stepItem: { flex: 1, gap: Spacing.one },
  stepBar: { height: 4, borderRadius: 2 },
  drop: { borderWidth: 2, borderStyle: 'dashed', borderRadius: Radius.lg, padding: Spacing.five, alignItems: 'center', gap: Spacing.two },
  clipRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, padding: Spacing.two },
  alias: { position: 'absolute', left: 4, top: 4, color: '#fff', fontSize: 11, fontWeight: '800', backgroundColor: 'rgba(0,0,0,0.55)', paddingHorizontal: 4, borderRadius: 4, overflow: 'hidden' },
  thumb: { width: 54, height: 96, borderRadius: Radius.sm, overflow: 'hidden' },
  mini: { width: 30, height: 54, borderRadius: 6, overflow: 'hidden' },
  actions: { alignItems: 'flex-end', gap: Spacing.one },
  arrows: { flexDirection: 'row', gap: Spacing.one },
  arrow: { width: 32, height: 32, borderRadius: Radius.sm, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  small: { minHeight: 32, paddingHorizontal: Spacing.two },
  row: { flexDirection: 'row', gap: Spacing.two },
  hero: { width: '100%', maxWidth: 300, aspectRatio: 9 / 16, alignSelf: 'center', borderRadius: Radius.lg + 4, overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center' },
  heroShade: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.25)' },
  play: { width: 64, height: 64, borderRadius: 32, backgroundColor: 'rgba(0,0,0,0.55)', alignItems: 'center', justifyContent: 'center' },
  heroText: { position: 'absolute', left: Spacing.three, right: Spacing.three, bottom: Spacing.three },
  heroTitle: { color: '#fff', fontSize: 18, fontWeight: '800' },
  heroSub: { color: 'rgba(255,255,255,0.85)', fontSize: 14 },
  video: { position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' },
  heroTrack: { width: '100%', height: 8, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.25)', overflow: 'hidden' },
  heroFill: { height: '100%', borderRadius: 4 },
  ask: { borderWidth: 1, borderRadius: Radius.md, padding: Spacing.three, fontSize: 17, minHeight: 96, textAlignVertical: 'top' },
  ideas: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  idea: { borderWidth: 1, borderRadius: Radius.pill, paddingHorizontal: Spacing.three, paddingVertical: 7 },
  version: { width: 76, gap: 4, borderWidth: 2, borderRadius: Radius.md, padding: 3 },
  versionThumb: { width: '100%', aspectRatio: 9 / 16, borderRadius: Radius.sm, overflow: 'hidden' },
  center: { alignItems: 'center', justifyContent: 'center' },
  badge: { position: 'absolute', left: 3, bottom: 3, color: '#fff', fontSize: 9, fontWeight: '800', paddingHorizontal: 4, borderRadius: 4, overflow: 'hidden' },
  linkRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.two, borderWidth: 1, borderRadius: Radius.md, padding: Spacing.two },
});
