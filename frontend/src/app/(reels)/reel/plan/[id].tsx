/**
 * The editor, built like a phone video editor:
 *   - a live preview on top (plays the edit itself, no export needed)
 *   - a timeline below: parts, captions, effects and sounds, with the playhead in the middle
 *   - tap anything to select it: drag to move or reorder, drag its edges to trim,
 *     and the bar at the bottom shows what else you can do with it
 *   - "+ Caption" / "+ Effect" add at the playhead, so you choose where by scrolling to it
 * Changes save by themselves (the server's validator checks them; no AI). Undo steps back.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { ConfirmAI } from '@/components/confirm-ai';
import { Preview } from '@/components/editor/preview';
import { type DragKind, type DragPhase, PART_COLORS, type Sel, Timeline } from '@/components/editor/timeline';
import { ExportSheet } from '@/components/export-sheet';
import { MusicPicker } from '@/components/music-picker';
import { Sheet } from '@/components/sheet';
import { Button, Card, Choice, Field, Loading, Message, SectionTitle, formatSeconds } from '@/components/ui';
import { VoiceButton } from '@/components/voice-button';
import { BottomTabInset, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { fmt, readableSeconds, round, shotLength, timeline } from '@/lib/plan';
import { soundCues } from '@/lib/sfx-cues';
import type { Caption, CaptionPosition, Clip, EditPlan, Effect, EffectType, Look, MotionEffectInfo, Project, Shot } from '@/lib/types';

type SheetName = 'caption' | 'effect' | 'library' | 'clip' | 'sound' | 'story' | null;

const TAB_PAD = Platform.OS === 'web' ? 64 : BottomTabInset;
const POSITIONS: { value: CaptionPosition; label: string }[] = [
  { value: 'upper_third', label: 'Top' },
  { value: 'middle', label: 'Middle' },
  { value: 'lower_middle', label: 'Bottom' },
];
const EFFECTS: Record<EffectType, { label: string; hint: string; len: number; icon: string }> = {
  punch_in: { label: 'Punch in', hint: 'Quick zoom onto your face', len: 1, icon: '🔍' },
  slow_push: { label: 'Slow push', hint: 'Slow cinematic push in', len: 3, icon: '🎥' },
  spotlight: { label: 'Spotlight', hint: 'Everything but you goes dark', len: 2, icon: '🔦' },
  grade: { label: 'Colour look', hint: 'A mood for this stretch', len: 4, icon: '🎨' },
  freeze_frame: { label: 'Freeze frame', hint: 'Picture holds, a label points at you', len: 1.5, icon: '⏸️' },
  flash: { label: 'Flash', hint: 'White flash on a beat', len: 0.3, icon: '⚡' },
  countdown: { label: 'Countdown', hint: 'Big 3-2-1 above you', len: 2, icon: '3️⃣' },
  backdrop_word: { label: 'Word behind you', hint: 'A giant word behind your head', len: 2.5, icon: '🅰️' },
  // motion graphics (drawn on the server; the gallery shows each one moving)
  chat: { label: 'Chat', hint: 'Messages pop in one by one', len: 3.5, icon: '💬' },
  counter: { label: 'Counter', hint: 'A big number counts up', len: 3, icon: '🔢' },
  graph: { label: 'Graph', hint: 'Bars rise to your numbers', len: 3.5, icon: '📊' },
  widgets: { label: 'Glass widgets', hint: 'Up to 4 stat cards pop in', len: 3.5, icon: '🧊' },
  checklist: { label: 'Checklist', hint: 'Items tick off one by one', len: 3.5, icon: '✅' },
  progress: { label: 'Progress', hint: 'A bar fills: day 12 of 30', len: 3, icon: '📈' },
  location: { label: 'Location', hint: 'A pin drops on a place', len: 3, icon: '📍' },
  name_card: { label: 'Name card', hint: 'Your name and role slide in', len: 3, icon: '🪪' },
  follow: { label: 'Follow', hint: 'A follow button gets tapped', len: 2.5, icon: '➕' },
  emoji_burst: { label: 'Emoji burst', hint: 'Emojis float up', len: 2.5, icon: '🎉' },
  poll: { label: 'Poll', hint: 'A question with answer bars', len: 3.5, icon: '🗳️' },
  timer: { label: 'Timer', hint: 'A clock ring runs down', len: 3, icon: '⏱️' },
  notification: { label: 'Notification', hint: 'A phone notification drops in', len: 3, icon: '🔔' },
  price_tag: { label: 'Price tag', hint: 'A price sticker spins in', len: 3, icon: '🏷️' },
};
const MOTION = new Set<EffectType>(['chat', 'counter', 'graph', 'widgets', 'checklist', 'progress', 'location', 'name_card',
  'follow', 'emoji_burst', 'poll', 'timer', 'notification', 'price_tag']);
// how each graphic uses its fields, for the edit sheet
const MOTION_FIELDS: Partial<Record<EffectType, { title?: string; items?: string; numbers?: string; unit?: boolean }>> = {
  chat: { title: 'Chat name (optional)', items: "One message per line. Start with 'Me:' for your side, 'Name:' for others." },
  counter: { title: 'Label, e.g. Push-ups', numbers: 'From, to - e.g. 0, 100', unit: true },
  graph: { title: 'Title', items: 'Labels, one per line (Mon, Tue...)', numbers: 'Values, e.g. 3, 5, 4, 8', unit: true },
  widgets: { items: 'Up to 4, one per line: icon | label | value (🔥 | Calories | 120)' },
  checklist: { title: 'Title, e.g. Breakfast', items: 'Items, one per line' },
  progress: { title: 'Label, e.g. Day', numbers: 'Now, total - e.g. 12, 30', unit: true },
  location: { title: 'Place', items: 'Area (optional)' },
  name_card: { title: 'Name', items: 'Role, e.g. Founder' },
  follow: { title: 'Your @handle' },
  emoji_burst: { items: 'Emojis, one per line' },
  poll: { title: 'Question', items: 'Answers, one per line', numbers: 'Percents, e.g. 64, 36' },
  timer: { title: 'Label, e.g. Plank', numbers: 'Seconds, e.g. 60' },
  notification: { title: 'From, e.g. Mom', items: 'Message' },
  price_tag: { title: 'Label, e.g. SALE', numbers: 'Price, old price - e.g. 499, 999', unit: true },
};
const TEXT_EFFECTS: Partial<Record<EffectType, { placeholder: string; max: number; label: string }>> = {
  freeze_frame: { placeholder: "e.g. That's me", max: 40, label: 'Label' },
  backdrop_word: { placeholder: 'e.g. DAY 1', max: 16, label: 'Word' },
};
const LOOKS: { value: Look; label: string }[] = [
  { value: 'moody', label: 'Moody' }, { value: 'bw', label: 'B&W' }, { value: 'warm', label: 'Warm' },
  { value: 'cool', label: 'Cool' }, { value: 'pop', label: 'Pop' },
];

export default function PlanScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) });
  if (q.isPending) return <Loading />;
  if (q.isError) return <Message title="Couldn't load this reel" body={q.error.message} />;
  if (!q.data.plan) return <Message title="No edit yet" body="Go back and tap Edit my reel first." />;
  return <Editor project={q.data} />;
}

const partName = (s: Shot, i: number) => {
  const p = (s.purpose || '').trim();
  return p ? p[0].toUpperCase() + p.slice(1) : `Part ${i + 1}`;
};

/** A new part from a whole clip (up to 6 s); trim it on the timeline. */
function newShot(alias: string, clip?: Clip): Shot {
  const len = clip?.duration_s ?? 3;
  return { clip: alias, in_s: 0, out_s: Math.min(len, 6), speed: 1, zoom_from: 1, zoom_to: 1, focus_x: 0.5, focus_y: 0.5, keep_audio: !!clip?.has_speech, purpose: 'added by you' };
}

function Editor({ project }: { project: Project }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [local, setLocal] = useState<EditPlan | null>(null); // edits not on the server yet
  const [sel, setSel] = useState<Sel>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [pps, setPps] = useState(48);
  const [sheet, setSheet] = useState<SheetName>(null);
  const [exporting, setExporting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [history, setHistory] = useState<EditPlan[]>([]);
  const snap = useRef<EditPlan | null>(null);

  const draft = local ?? project.plan!;
  const localRef = useRef(local);
  useLayoutEffect(() => {
    localRef.current = local;
  });
  const tl = timeline(draft);
  const cues = useMemo(() => soundCues(draft, tl.total), [draft, tl.total]);
  const clips = useMemo(() => {
    const m: Record<string, Clip> = {};
    project.clips.forEach((c, i) => (m[`C${i + 1}`] = c));
    return m;
  }, [project.clips]);

  /** One undoable change. */
  const edit = (fn: (p: EditPlan) => void) => {
    setHistory((h) => [...h.slice(-30), draft]);
    const next = structuredClone(draft);
    fn(next);
    setLocal(next);
  };
  const undo = () => {
    const prev = history.at(-1);
    if (!prev) return;
    setHistory((h) => h.slice(0, -1));
    setLocal(prev);
  };

  // save by itself a moment after the last change (not mid-drag)
  const save = useMutation({
    mutationFn: (plan: EditPlan) => api.savePlan(project.id, plan),
    onSuccess: (p, sent) => {
      qc.setQueryData(['project', project.id], p);
      if (localRef.current === sent) setLocal(null); // nothing new since: show the server's checked copy
    },
  });
  useEffect(() => {
    if (!local || dragging) return;
    const id = setTimeout(() => save.mutate(local), 1200);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [local, dragging]);
  useEffect(() => () => {
    if (localRef.current) api.savePlan(project.id, localRef.current).then((p) => qc.setQueryData(['project', project.id], p)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const exportNow = async () => {
    setPlaying(false);
    if (local) await save.mutateAsync(local);
    setExporting(true);
  };

  // dragging on the timeline: every move is applied to a copy taken when the drag began
  const onDrag = (target: { kind: 'part' | 'caption' | 'effect'; i: number }, how: DragKind, phase: DragPhase, dt: number) => {
    if (phase === 'begin') {
      setPlaying(false);
      setDragging(true);
      snap.current = structuredClone(draft);
      return;
    }
    const base = snap.current;
    if (phase === 'end') {
      setDragging(false);
      snap.current = null;
      // one undo step per drag that changed something (a part's reorder records its own step)
      if (base && !(target.kind === 'part' && how === 'move') && Math.abs(dt) > 0.01) setHistory((h) => [...h.slice(-30), base]);
    }
    if (!base || (target.kind === 'part' && how === 'move')) return;
    const p = structuredClone(base);
    if (target.kind === 'part') {
      const s0 = base.shots[target.i];
      const sh = p.shots[target.i];
      const sp = s0.speed || 1;
      const clipLen = clips[s0.clip]?.duration_s ?? s0.out_s;
      if (how === 'start') sh.in_s = round(Math.max(0, Math.min(s0.in_s + dt * sp, s0.out_s - 0.3)), 0.05);
      else sh.out_s = round(Math.min(clipLen, Math.max(s0.out_s + dt * sp, s0.in_s + 0.3)), 0.05);
    } else {
      const list = (target.kind === 'caption' ? p.captions : p.effects ?? []) as (Caption | Effect)[];
      const x0 = (target.kind === 'caption' ? base.captions : base.effects ?? [])[target.i];
      const x = list[target.i];
      const limit = target.kind === 'caption' ? tl.total : tl.footage;
      const len = x0.end_s - x0.start_s;
      if (how === 'move') {
        x.start_s = round(Math.max(0, Math.min(x0.start_s + dt, limit - len)), 0.05);
        x.end_s = round(x.start_s + len, 0.05);
      } else if (how === 'start') {
        x.start_s = round(Math.max(0, Math.min(x0.start_s + dt, x0.end_s - 0.3)), 0.05);
      } else {
        x.end_s = round(Math.min(limit, Math.max(x0.end_s + dt, x0.start_s + 0.3)), 0.05);
      }
      if (how !== 'end') setTime(x.start_s); // show the frame where it now starts
    }
    setLocal(p);
  };

  const reorder = (from: number, to: number) => {
    edit((p) => {
      const [s] = p.shots.splice(from, 1);
      p.shots.splice(to, 0, s);
    });
    setSel({ kind: 'part', i: to });
  };

  const addCaption = (at: number) => {
    const start = round(Math.max(0, Math.min(at, tl.total - 1)), 0.05);
    const i = draft.captions.filter((c) => c.start_s <= start).length;
    edit((p) => { p.captions.splice(i, 0, { text: 'New caption', start_s: start, end_s: round(Math.min(tl.total, start + 2), 0.05), position: 'lower_middle', highlight: null }); });
    setSel({ kind: 'caption', i });
    setSheet('caption');
  };
  const addEffect = (type: EffectType, sample?: MotionEffectInfo['sample']) => {
    const len = EFFECTS[type].len;
    const start = round(Math.max(0, Math.min(time, tl.footage - len)), 0.05);
    const e: Effect = {
      type, start_s: start, end_s: round(Math.min(tl.footage, start + len), 0.05),
      text: type === 'freeze_frame' ? 'Look here' : type === 'backdrop_word' ? (draft.title.split(/\s+/).slice(0, 2).join(' ').slice(0, 16).toUpperCase() || 'DAY 1') : null,
      look: type === 'grade' ? 'moody' : null,
    };
    if (MOTION.has(type) && sample) {
      Object.assign(e, { text: sample.text ?? null, items: sample.items ?? [], numbers: sample.numbers ?? [], unit: sample.unit ?? null, position: null, behind: false });
    }
    const i = (draft.effects ?? []).filter((x) => x.start_s <= start).length;
    edit((p) => { (p.effects ??= []).splice(i, 0, e); });
    setSel({ kind: 'effect', i });
    setSheet(TEXT_EFFECTS[type] || type === 'grade' || MOTION.has(type) ? 'effect' : null);
  };
  const addPart = (alias: string) => {
    const under = tl.shots.findIndex((s) => time < s.end);
    const i = (under < 0 ? draft.shots.length - 1 : under) + 1;
    edit((p) => { p.shots.splice(i, 0, newShot(alias, clips[alias])); });
    setSel({ kind: 'part', i });
    setSheet(null);
  };

  const selected = sel && (
    sel.kind === 'part' ? draft.shots[sel.i] : sel.kind === 'caption' ? draft.captions[sel.i] : sel.kind === 'effect' ? draft.effects?.[sel.i] : cues[sel.i]
  ) ? sel : null;

  return (
    <View style={[styles.screen, { backgroundColor: t.background, paddingBottom: TAB_PAD }]}>
      <Stack.Screen options={{
        title: `${fmt(tl.total)} reel`,
        headerRight: () => <Button label="Export" style={styles.exportBtn} loading={save.isPending && exporting} onPress={exportNow} />,
      }} />

      <View style={styles.stage}>
        <Preview plan={draft} clips={clips} shots={tl.shots} footage={tl.footage} total={tl.total} time={time} playing={playing}
          cues={cues} onTime={setTime} onEnd={() => setPlaying(false)} />
      </View>

      <View style={styles.transport}>
        <Pressable onPress={() => setPlaying((p) => !p)} style={[styles.play, { backgroundColor: t.text }]} accessibilityLabel={playing ? 'Pause' : 'Play'}>
          <Text style={{ color: t.background, fontSize: 16, fontWeight: '800' }}>{playing ? '❚❚' : '▶'}</Text>
        </Pressable>
        <Text style={{ color: t.text, fontVariant: ['tabular-nums'], fontWeight: '600' }}>{fmt(time)} <Text style={{ color: t.textSecondary }}>/ {fmt(tl.total)}</Text></Text>
        <View style={{ flex: 1 }} />
        <Text style={{ color: save.isError ? t.danger : t.textSecondary, fontSize: 12 }}>
          {save.isError ? 'Not saved' : save.isPending || local ? 'Saving…' : 'Saved ✓'}
        </Text>
        <Small label="↩︎" onPress={undo} disabled={!history.length} />
        <Small label="−" onPress={() => setPps((x) => Math.max(16, x / 1.5))} />
        <Small label="+" onPress={() => setPps((x) => Math.min(160, x * 1.5))} />
      </View>

      <Timeline plan={draft} clips={clips} starts={tl.shots.map((s) => s.start)} total={tl.total} time={time} pps={pps}
        sel={selected} playing={playing} cues={cues} onSeek={setTime}
        onSelect={(s) => { setSel(s); if (s && s.kind !== 'cue') setPlaying(false); }}
        onDrag={onDrag} onReorder={reorder} />

      <ActionBar sel={selected} draft={draft} cues={cues} time={time} tl={tl} edit={edit}
        onSheet={setSheet} onSelect={setSel} onAddCaption={addCaption} onSeek={setTime} />

      {/* sheets */}
      {sheet === 'caption' && selected?.kind === 'caption' ? (
        <CaptionSheet i={selected.i} c={draft.captions[selected.i]} edit={edit} onClose={() => setSheet(null)}
          onDelete={() => { edit((p) => { p.captions.splice(selected.i, 1); }); setSel(null); setSheet(null); }} />
      ) : null}
      {sheet === 'effect' && selected?.kind === 'effect' && draft.effects?.[selected.i] ? (
        <EffectSheet i={selected.i} e={draft.effects[selected.i]} edit={edit} onClose={() => setSheet(null)} />
      ) : null}
      <LibrarySheet open={sheet === 'library'} at={time} onClose={() => setSheet(null)} onPick={addEffect} />
      <ClipSheet open={sheet === 'clip'} clips={project.clips} onClose={() => setSheet(null)} onPick={addPart} />
      <SoundSheet open={sheet === 'sound'} draft={draft} cues={cues} edit={edit} onClose={() => setSheet(null)}
        onSeek={(at) => { setTime(at); setSheet(null); }} />
      <Sheet open={sheet === 'story'} onClose={() => setSheet(null)} title="Story & details">
        <Story project={project} draft={draft} dirty={!!local} edit={edit} />
      </Sheet>
      <ExportSheet projectId={project.id} title={project.title} open={exporting} onClose={() => setExporting(false)} />
    </View>
  );
}

function Small({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) {
  const t = useTheme();
  return (
    <Pressable onPress={disabled ? undefined : onPress} hitSlop={6} style={[styles.smallBtn, { backgroundColor: t.backgroundElement, opacity: disabled ? 0.35 : 1 }]}>
      <Text style={{ color: t.text, fontSize: 16, fontWeight: '700' }}>{label}</Text>
    </Pressable>
  );
}

// the bar under the timeline: tools when nothing is selected, actions for what is ---------------

function Tool({ icon, label, onPress, active, danger }: { icon: string; label: string; onPress: () => void; active?: boolean; danger?: boolean }) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.tool, { backgroundColor: active ? t.accent + '22' : 'transparent', opacity: pressed ? 0.6 : 1 }]}>
      <Text style={{ fontSize: 20 }}>{icon}</Text>
      <Text style={{ color: danger ? t.danger : active ? t.accent : t.text, fontSize: 11, fontWeight: '600' }} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

function ActionBar({ sel, draft, cues, time, tl, edit, onSheet, onSelect, onAddCaption, onSeek }: {
  sel: Sel; draft: EditPlan; cues: ReturnType<typeof soundCues>; time: number; tl: ReturnType<typeof timeline>;
  edit: (fn: (p: EditPlan) => void) => void; onSheet: (s: SheetName) => void; onSelect: (s: Sel) => void;
  onAddCaption: (at: number) => void; onSeek: (t: number) => void;
}) {
  const t = useTheme();
  let title = '';
  let hint = 'Scroll the timeline to move the playhead. Tap anything to change it.';
  let tools: React.ReactNode;

  if (!sel) {
    tools = (
      <>
        <Tool icon="💬" label="+ Caption" onPress={() => onAddCaption(time)} />
        <Tool icon="✨" label="+ Effect" onPress={() => onSheet('library')} />
        <Tool icon="🎬" label="+ Clip" onPress={() => onSheet('clip')} />
        <Tool icon="🔊" label={`Sounds: ${draft.sound_effects ?? 'subtle'}`} onPress={() => onSheet('sound')} />
        <Tool icon="📝" label="Story" onPress={() => onSheet('story')} />
      </>
    );
    hint = `New captions and effects start at the playhead (${fmt(time)}). ${hint}`;
  } else if (sel.kind === 'part') {
    const s = draft.shots[sel.i];
    title = `Part ${sel.i + 1} · ${partName(s, sel.i)} · ${shotLength(s).toFixed(1)}s`;
    hint = 'Drag it to change the order. Drag its white edges to trim.';
    const span = tl.shots[sel.i];
    tools = (
      <>
        <Tool icon={s.keep_audio ? '🔊' : '🔇'} label={s.keep_audio ? 'Voice on' : 'Muted'} active={!s.keep_audio}
          onPress={() => edit((p) => { p.shots[sel.i].keep_audio = !p.shots[sel.i].keep_audio; })} />
        <Tool icon="💬" label="Caption here" onPress={() => onAddCaption(span && time >= span.start && time < span.end ? time : span?.start ?? time)} />
        <Tool icon="⧉" label="Duplicate" onPress={() => { edit((p) => { p.shots.splice(sel.i + 1, 0, { ...p.shots[sel.i] }); }); onSelect({ kind: 'part', i: sel.i + 1 }); }} />
        {draft.shots.length > 1 ? <Tool icon="🗑" label="Delete" danger onPress={() => { edit((p) => { p.shots.splice(sel.i, 1); }); onSelect(null); }} /> : null}
        <Tool icon="✓" label="Done" onPress={() => onSelect(null)} />
      </>
    );
  } else if (sel.kind === 'caption') {
    const c = draft.captions[sel.i];
    title = `Caption · ${fmt(c.start_s)}–${fmt(c.end_s)}`;
    hint = readableSeconds(c.text) - (c.end_s - c.start_s) > 0.05
      ? `A bit fast to read: drag the right edge to about ${readableSeconds(c.text).toFixed(1)}s.`
      : 'Drag it to move it. Drag its white edges to make it longer or shorter.';
    tools = (
      <>
        <Tool icon="✏️" label="Edit text" onPress={() => onSheet('caption')} />
        {POSITIONS.map((pos) => (
          <Tool key={pos.value} icon={pos.value === 'upper_third' ? '⬆️' : pos.value === 'middle' ? '⏺️' : '⬇️'} label={pos.label}
            active={c.position === pos.value} onPress={() => edit((p) => { p.captions[sel.i].position = pos.value; })} />
        ))}
        <Tool icon="🗑" label="Delete" danger onPress={() => { edit((p) => { p.captions.splice(sel.i, 1); }); onSelect(null); }} />
      </>
    );
  } else if (sel.kind === 'effect') {
    const e = draft.effects![sel.i];
    const info = EFFECTS[e.type];
    title = `${info?.icon ?? '✨'} ${info?.label ?? e.type} · ${fmt(e.start_s)}–${fmt(e.end_s)}`;
    hint = 'Drag it to choose when it happens. Drag its white edges to change how long.';
    const sound = cues.find((q) => q.why === info?.label && q.at >= e.start_s - 0.01 && q.at <= e.end_s + 0.3);
    tools = (
      <>
        {TEXT_EFFECTS[e.type] || e.type === 'grade' || MOTION.has(e.type) ? (
          <Tool icon={e.type === 'grade' ? '🎨' : '✏️'} label={e.type === 'grade' ? 'Look' : MOTION.has(e.type) ? 'Edit' : TEXT_EFFECTS[e.type]!.label} onPress={() => onSheet('effect')} />
        ) : null}
        <Tool icon="▶" label="Watch it" onPress={() => onSeek(Math.max(0, e.start_s - 0.5))} />
        {sound ? <Tool icon={sound.icon} label={`Sound ${fmt(sound.at)}`} onPress={() => onSheet('sound')} /> : null}
        <Tool icon="🗑" label="Delete" danger onPress={() => { edit((p) => { p.effects!.splice(sel.i, 1); }); onSelect(null); }} />
        <Tool icon="✓" label="Done" onPress={() => onSelect(null)} />
      </>
    );
  } else {
    const c = cues[sel.i];
    title = `${c.icon} ${c.name} at ${fmt(c.at)}`;
    hint = `Plays with: ${c.why}. Move that and the sound moves with it.`;
    tools = (
      <>
        <Tool icon="▶" label="Hear it" onPress={() => onSeek(Math.max(0, c.at - 0.5))} />
        <Tool icon="🔊" label="Sound options" onPress={() => onSheet('sound')} />
        <Tool icon="✓" label="Done" onPress={() => onSelect(null)} />
      </>
    );
  }

  return (
    <View style={[styles.bar, { borderColor: t.border, backgroundColor: t.backgroundElement }]}>
      {title ? <Text style={{ color: t.text, fontWeight: '700' }} numberOfLines={1}>{title}</Text> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tools}>{tools}</ScrollView>
      <Text style={{ color: t.textSecondary, fontSize: 12 }} numberOfLines={2}>{hint}</Text>
    </View>
  );
}

// sheets ------------------------------------------------------------------------------

function CaptionSheet({ i, c, edit, onClose, onDelete }: { i: number; c: Caption; edit: (fn: (p: EditPlan) => void) => void; onClose: () => void; onDelete: () => void }) {
  const t = useTheme();
  const words = c.text.split(/\s+/).filter(Boolean);
  return (
    <Sheet open onClose={onClose} title="Caption" footer={<Button label="Done" style={{ flex: 1 }} onPress={onClose} />}>
      <TextInput value={c.text} onChangeText={(text) => edit((p) => { p.captions[i].text = text; })}
        style={[styles.input, { color: t.text, borderColor: t.border, backgroundColor: t.background }]} multiline maxLength={140}
        autoFocus={c.text === 'New caption'} selectTextOnFocus />
      <SectionTitle>Highlight a word</SectionTitle>
      <View style={styles.choices}>
        <Choice label="None" selected={!c.highlight} onPress={() => edit((p) => { p.captions[i].highlight = null; })} />
        {words.slice(0, 12).map((w, k) => {
          const clean = w.replace(/[^\p{L}\p{N}%.'-]/gu, '');
          return clean ? <Choice key={`${w}-${k}`} label={clean} selected={c.highlight === clean} onPress={() => edit((p) => { p.captions[i].highlight = clean; })} /> : null;
        })}
      </View>
      <SectionTitle>Where on screen</SectionTitle>
      <View style={styles.choices}>
        {POSITIONS.map((pos) => (
          <Choice key={pos.value} label={pos.label} selected={c.position === pos.value} onPress={() => edit((p) => { p.captions[i].position = pos.value; })} />
        ))}
      </View>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>If it would cover your face, it moves by itself. To change when it shows, drag it on the timeline.</Text>
      <Button label="Delete caption" kind="ghost" onPress={onDelete} />
    </Sheet>
  );
}

function EffectSheet({ i, e, edit, onClose }: { i: number; e: Effect; edit: (fn: (p: EditPlan) => void) => void; onClose: () => void }) {
  const t = useTheme();
  const info = EFFECTS[e.type];
  return (
    <Sheet open onClose={onClose} title={`${info?.icon ?? '✨'} ${info?.label ?? e.type}`} footer={<Button label="Done" style={{ flex: 1 }} onPress={onClose} />}>
      <Text style={{ color: t.textSecondary }}>{info?.hint}</Text>
      {TEXT_EFFECTS[e.type] ? (
        <TextInput value={e.text ?? ''} placeholder={TEXT_EFFECTS[e.type]!.placeholder} placeholderTextColor={t.textSecondary}
          autoCapitalize={e.type === 'backdrop_word' ? 'characters' : 'sentences'} autoFocus
          onChangeText={(text) => edit((p) => { p.effects![i].text = text; })}
          style={[styles.input, { color: t.text, borderColor: t.border, backgroundColor: t.background }]} maxLength={TEXT_EFFECTS[e.type]!.max} />
      ) : null}
      {e.type === 'grade' ? (
        <View style={styles.choices}>
          {LOOKS.map((l) => <Choice key={l.value} label={l.label} selected={(e.look ?? 'moody') === l.value} onPress={() => edit((p) => { p.effects![i].look = l.value; })} />)}
        </View>
      ) : null}
      {MOTION.has(e.type) ? <MotionFields i={i} e={e} edit={edit} /> : null}
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>To change when it happens, drag it on the timeline.</Text>
    </Sheet>
  );
}

/** A motion graphic's inputs: title, items (one per line), numbers, unit, where it sits, in front of or behind you. */
function MotionFields({ i, e, edit }: { i: number; e: Effect; edit: (fn: (p: EditPlan) => void) => void }) {
  const t = useTheme();
  const f = MOTION_FIELDS[e.type] ?? {};
  // numbers are typed as text ("0, 100") and stored as numbers; keep the typed text while editing
  const [nums, setNums] = useState((e.numbers ?? []).join(', '));
  const input = [styles.input, { color: t.text, borderColor: t.border, backgroundColor: t.background }];
  return (
    <View style={{ gap: Spacing.two }}>
      {f.title ? (
        <TextInput value={e.text ?? ''} placeholder={f.title} placeholderTextColor={t.textSecondary} maxLength={50}
          onChangeText={(text) => edit((p) => { p.effects![i].text = text; })} style={input} />
      ) : null}
      {f.items ? (
        <TextInput value={(e.items ?? []).join('\n')} placeholder={f.items} placeholderTextColor={t.textSecondary} multiline
          onChangeText={(text) => edit((p) => { p.effects![i].items = text.split('\n').slice(0, 6); })} style={[input, { minHeight: 90 }]} />
      ) : null}
      {f.numbers ? (
        <TextInput value={nums} placeholder={f.numbers} placeholderTextColor={t.textSecondary} keyboardType="numbers-and-punctuation"
          onChangeText={(text) => {
            setNums(text);
            const values = text.split(/[,\s]+/).map((x) => parseFloat(x)).filter((x) => Number.isFinite(x));
            edit((p) => { p.effects![i].numbers = values.slice(0, 8); });
          }} style={input} />
      ) : null}
      {f.unit ? (
        <TextInput value={e.unit ?? ''} placeholder="Unit (optional): km, reps, %, ₹" placeholderTextColor={t.textSecondary} maxLength={8}
          onChangeText={(text) => edit((p) => { p.effects![i].unit = text || null; })} style={input} />
      ) : null}
      <Text style={{ color: t.textSecondary, fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1 }}>Where</Text>
      <View style={styles.choices}>
        {([null, 'top', 'middle', 'bottom'] as const).map((pos) => (
          <Choice key={String(pos)} label={pos ? pos[0].toUpperCase() + pos.slice(1) : 'Usual spot'} selected={(e.position ?? null) === pos}
            onPress={() => edit((p) => { p.effects![i].position = pos; })} />
        ))}
      </View>
      <View style={styles.choices}>
        <Choice label="In front of you" selected={!e.behind} onPress={() => edit((p) => { p.effects![i].behind = false; })} />
        <Choice label="Behind you" selected={!!e.behind} onPress={() => edit((p) => { p.effects![i].behind = true; })} />
      </View>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>Graphics show as a label in this preview; export to see them move.</Text>
    </View>
  );
}

function LibrarySheet({ open, at, onClose, onPick }: {
  open: boolean; at: number; onClose: () => void; onPick: (type: EffectType, sample?: MotionEffectInfo['sample']) => void;
}) {
  const t = useTheme();
  const graphics = useQuery({ queryKey: ['motion-effects'], queryFn: api.motionEffects, staleTime: 10 * 60_000, enabled: open });
  return (
    <Sheet open={open} onClose={onClose} title="Add an effect">
      <Text style={{ color: t.textSecondary }}>It starts at the playhead, {fmt(at)}. You can drag it on the timeline after.</Text>
      <SectionTitle>Graphics</SectionTitle>
      {graphics.isLoading ? <Text style={{ color: t.textSecondary }}>Loading…</Text> : null}
      <View style={styles.lib}>
        {(graphics.data ?? []).map((g) => (
          <Pressable key={g.type} onPress={() => onPick(g.type, g.sample)} style={({ pressed }) => [styles.gfxTile, { opacity: pressed ? 0.7 : 1 }]}>
            <View style={[styles.gfxThumb, { borderColor: t.border, backgroundColor: t.backgroundSelected }]}>
              <Image source={{ uri: g.preview_url }} style={StyleSheet.absoluteFill} contentFit="cover" autoplay />
            </View>
            <Text style={{ color: t.text, fontWeight: '700', fontSize: 13 }} numberOfLines={1}>{g.name}</Text>
            <Text style={{ color: t.textSecondary, fontSize: 11 }} numberOfLines={2}>{g.help}</Text>
          </Pressable>
        ))}
      </View>
      <SectionTitle>Camera & light</SectionTitle>
      <View style={styles.lib}>
        {(Object.keys(EFFECTS) as EffectType[]).filter((k) => !MOTION.has(k)).map((k) => (
          <Pressable key={k} onPress={() => onPick(k)} style={({ pressed }) => [styles.libTile, { backgroundColor: t.background, borderColor: t.border, opacity: pressed ? 0.7 : 1 }]}>
            <Text style={{ fontSize: 30 }}>{EFFECTS[k].icon}</Text>
            <Text style={{ color: t.text, fontWeight: '700', fontSize: 13, textAlign: 'center' }}>{EFFECTS[k].label}</Text>
            <Text style={{ color: t.textSecondary, fontSize: 11, textAlign: 'center' }} numberOfLines={2}>{EFFECTS[k].hint}</Text>
          </Pressable>
        ))}
      </View>
    </Sheet>
  );
}

function ClipSheet({ open, clips, onClose, onPick }: { open: boolean; clips: Clip[]; onClose: () => void; onPick: (alias: string) => void }) {
  const t = useTheme();
  return (
    <Sheet open={open} onClose={onClose} title="Add a clip">
      <Text style={{ color: t.textSecondary }}>It goes right after the part under the playhead. Trim it on the timeline.</Text>
      <View style={styles.lib}>
        {clips.map((c, i) => c.status === 'ready' ? (
          <Pressable key={c.id} onPress={() => onPick(`C${i + 1}`)} style={styles.clipTile}>
            <View style={[styles.clipThumb, { backgroundColor: t.backgroundSelected, borderColor: PART_COLORS[i % PART_COLORS.length] }]}>
              {c.thumbnail_url ? <Image source={{ uri: c.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
            </View>
            <Text style={{ color: t.text, fontWeight: '600', fontSize: 13 }}>C{i + 1} · {formatSeconds(c.duration_s ?? 0)}</Text>
          </Pressable>
        ) : null)}
      </View>
    </Sheet>
  );
}

const SOUND_MODES: { value: 'off' | 'subtle' | 'punchy'; label: string; body: string; icon: string }[] = [
  { value: 'off', label: 'Off', body: 'Just your voice.', icon: '🔈' },
  { value: 'subtle', label: 'Subtle', body: 'A soft whoosh on zooms, a hit when a word lands.', icon: '🔉' },
  { value: 'punchy', label: 'Punchy', body: 'Louder hits, and captions pop in.', icon: '🔊' },
];

function SoundSheet({ open, draft, cues, edit, onClose, onSeek }: {
  open: boolean; draft: EditPlan; cues: ReturnType<typeof soundCues>; edit: (fn: (p: EditPlan) => void) => void; onClose: () => void; onSeek: (t: number) => void;
}) {
  const t = useTheme();
  const mode = draft.sound_effects ?? 'subtle';
  return (
    <Sheet open={open} onClose={onClose} title="Sounds">
      {SOUND_MODES.map((m) => (
        <Pressable key={m.value} onPress={() => edit((p) => { p.sound_effects = m.value; })}
          style={[styles.row, { backgroundColor: mode === m.value ? t.accent + '18' : t.background, borderColor: mode === m.value ? t.accent : t.border }]}>
          <Text style={{ fontSize: 24 }}>{m.icon}</Text>
          <View style={{ flex: 1 }}>
            <Text style={{ color: mode === m.value ? t.accent : t.text, fontWeight: '700' }}>{m.label}</Text>
            <Text style={{ color: t.textSecondary, fontSize: 13 }}>{m.body}</Text>
          </View>
          {mode === m.value ? <Text style={{ color: t.accent, fontWeight: '800' }}>✓</Text> : null}
        </Pressable>
      ))}
      <SectionTitle>{cues.length ? `When you'll hear them · ${cues.length}` : 'No sounds yet'}</SectionTitle>
      {cues.length ? cues.map((c, i) => (
        <Pressable key={i} onPress={() => onSeek(Math.max(0, c.at - 0.5))} style={[styles.cueRow, { borderColor: t.border }]}>
          <Text style={{ color: t.textSecondary, width: 48, fontVariant: ['tabular-nums'] }}>{fmt(c.at)}</Text>
          <Text style={{ fontSize: 18 }}>{c.icon}</Text>
          <Text style={{ color: t.text, flex: 1 }}>{c.name} <Text style={{ color: t.textSecondary }}>· with {c.why}</Text></Text>
          <Text style={{ color: t.accent }}>▶</Text>
        </Pressable>
      )) : (
        <Text style={{ color: t.textSecondary }}>{mode === 'off' ? 'Sounds are off.' : 'Sounds come with effects. Add an effect and its sound appears on the 🔊 track.'}</Text>
      )}
      <SectionTitle>Music</SectionTitle>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>Starts on the beat and dips when you talk. Hear it in the next export.</Text>
      <MusicPicker active={open} value={draft.music.enabled ? draft.music.track ?? null : false}
        onChange={(v) => edit((p) => { p.music.enabled = v !== false; p.music.track = v || null; })} />
      {draft.music.enabled ? (
        <View style={styles.choices}>
          <Choice label="Under my voice" selected={draft.music.volume === 'low_under_voice'}
            onPress={() => edit((p) => { p.music.volume = 'low_under_voice'; })} />
          <Choice label="Balanced" selected={draft.music.volume === 'medium'}
            onPress={() => edit((p) => { p.music.volume = 'medium'; })} />
          <Choice label="Music first" selected={draft.music.volume === 'music_led'}
            onPress={() => edit((p) => { p.music.volume = 'music_led'; })} />
        </View>
      ) : null}
    </Sheet>
  );
}

// story: title, script, stats, cards - and re-edit with AI -------------------------------

function Story({ project, draft, dirty, edit }: { project: Project; draft: EditPlan; dirty: boolean; edit: (fn: (p: EditPlan) => void) => void }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [title, setTitle] = useState(project.title);
  const [script, setScript] = useState(project.script ?? '');
  const [stats, setStats] = useState(() => {
    const rows = Object.entries(project.stats ?? {}).map(([label, value]) => ({ label, value }));
    while (rows.length < 3) rows.push({ label: '', value: '' });
    return rows;
  });
  const [confirming, setConfirming] = useState(false);
  const statsObj = () => Object.fromEntries(stats.filter((s) => s.label.trim() && s.value.trim()).map((s) => [s.label.trim(), s.value.trim()]));
  const changed = title !== project.title || script !== (project.script ?? '') || JSON.stringify(statsObj()) !== JSON.stringify(project.stats ?? {});
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['project', project.id] });
    qc.invalidateQueries({ queryKey: ['projects'] });
  };
  const saveBrief = () => api.updateProject(project.id, { title: title.trim() || 'Untitled reel', script: script.trim() || null, stats: Object.keys(statsObj()).length ? statsObj() : null });
  const save = useMutation({ mutationFn: saveBrief, onSuccess: refresh });
  const replan = useMutation({
    mutationFn: async () => {
      if (changed) await saveBrief();
      return api.generatePlan(project.id);
    },
    onSuccess: () => {
      setConfirming(false);
      refresh();
      qc.invalidateQueries({ queryKey: ['ai-usage'] });
      router.back(); // the reel screen shows "Making your reel" and the new edit when it's ready
    },
  });

  return (
    <>
      <Field label="Title" value={title} onChangeText={setTitle} maxLength={200} />
      <Field label="Your story" value={script} onChangeText={setScript} multiline maxLength={4000} placeholder="What happens, the lines to show, what to highlight…" />
      <VoiceButton language={project.language} label="Say it instead" onText={(x) => setScript((s) => (s.trim() ? `${s.trim()}\n${x}` : x))} />
      <SectionTitle>Numbers for an end card (optional)</SectionTitle>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>For results worth showing: distance, followers, price, score… Leave empty for no card.</Text>
      {stats.map((s, i) => (
        <View key={i} style={{ flexDirection: 'row', gap: Spacing.two }}>
          <View style={{ flex: 1 }}>
            <Field value={s.label} placeholder="Label" maxLength={40} onChangeText={(v) => setStats((r) => r.map((x, j) => (j === i ? { ...x, label: v } : x)))} />
          </View>
          <View style={{ flex: 1.3 }}>
            <Field value={s.value} placeholder="Value" maxLength={40} onChangeText={(v) => setStats((r) => r.map((x, j) => (j === i ? { ...x, value: v } : x)))} />
          </View>
        </View>
      ))}
      {save.isError ? <Text style={{ color: t.danger }}>{save.error.message}</Text> : null}
      <Button label={save.isSuccess && !changed ? 'Saved ✓' : 'Save details'} kind="secondary" disabled={!changed} loading={save.isPending} onPress={() => save.mutate()} />

      {draft.overlays.length ? <SectionTitle>Cards in the reel</SectionTitle> : null}
      {draft.overlays.map((o, i) => (
        <Card key={i}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <Text style={{ color: t.text, fontWeight: '600' }}>{o.type === 'stats_card' ? 'Stats card' : 'Title'} · {fmt(o.start_s)}–{fmt(o.end_s)}</Text>
            <Button label="Remove" kind="ghost" style={{ minHeight: 32, paddingHorizontal: Spacing.two }} onPress={() => edit((p) => { p.overlays.splice(i, 1); })} />
          </View>
          {o.title ? <Text style={{ color: t.textSecondary }}>{o.title}</Text> : null}
          {o.items.length ? <Text style={{ color: t.accent, fontWeight: '600' }}>{o.items.map((x) => x.value).join('  ·  ')}</Text> : null}
        </Card>
      ))}

      {!dirty && project.plan_warnings.length ? (
        <Card>
          <Text style={{ color: t.text, fontWeight: '600' }}>Fixed automatically</Text>
          {project.plan_warnings.map((w) => <Text key={w} style={{ color: t.textSecondary, fontSize: 13 }}>• {w}</Text>)}
        </Card>
      ) : null}

      <SectionTitle>Start over</SectionTitle>
      {confirming ? (
        <ConfirmAI title="Write a new edit from these details?" note="The current edit will be replaced."
          confirmLabel="Re-edit" onConfirm={() => replan.mutate()} onCancel={() => setConfirming(false)}
          loading={replan.isPending} error={replan.isError ? replan.error.message : null} />
      ) : (
        <Button label="✨ Re-edit with AI" kind="secondary" onPress={() => setConfirming(true)} />
      )}
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  exportBtn: { minHeight: 34, paddingHorizontal: Spacing.three, marginRight: Spacing.two },
  stage: { flex: 1, minHeight: 200, paddingVertical: Spacing.two, alignItems: 'center' },
  transport: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, paddingHorizontal: Spacing.three, paddingBottom: Spacing.two },
  play: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  smallBtn: { width: 34, height: 34, borderRadius: Radius.sm, alignItems: 'center', justifyContent: 'center' },
  bar: { borderTopWidth: StyleSheet.hairlineWidth, paddingHorizontal: Spacing.three, paddingTop: Spacing.two, paddingBottom: Spacing.two, gap: 4, marginTop: Spacing.two },
  tools: { gap: Spacing.one },
  tool: { minWidth: 64, alignItems: 'center', gap: 2, paddingVertical: 6, paddingHorizontal: 6, borderRadius: Radius.md },
  input: { borderWidth: 1, borderRadius: Radius.md, padding: Spacing.three, fontSize: 17, minHeight: 52 },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  lib: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  libTile: { width: '23%', minWidth: 78, flexGrow: 1, borderWidth: StyleSheet.hairlineWidth, borderRadius: Radius.md, padding: Spacing.two, alignItems: 'center', gap: 2 },
  gfxTile: { width: '31%', maxWidth: 170, gap: 2 },
  gfxThumb: { width: '100%', aspectRatio: 9 / 16, borderRadius: Radius.md, borderWidth: 1, overflow: 'hidden' },
  clipTile: { width: 90, gap: 4 },
  clipThumb: { width: 90, height: 160, borderRadius: Radius.md, overflow: 'hidden', borderWidth: 2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, borderWidth: 1, borderRadius: Radius.md, padding: Spacing.three },
  cueRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: Spacing.two },
});
