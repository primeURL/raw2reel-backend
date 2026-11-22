/**
 * Review and edit the plan before rendering. Every edit here is free: saving goes through the
 * server's validator (no AI). Rendering is free too (CPU only) and makes a new version each time.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { ConfirmAI } from '@/components/confirm-ai';
import { Button, Card, Choice, Field, Loading, Message, ProgressBar, Screen, SectionTitle, StatusChip, formatSeconds } from '@/components/ui';
import { VoiceButton } from '@/components/voice-button';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { fmt, readableSeconds, round, shotLength, timeline } from '@/lib/plan';
import type { Caption, CaptionPosition, Clip, EditPlan, Effect, EffectType, Look, Project, Render, Shot } from '@/lib/types';

const SHOT_COLORS = ['#FF5A1F', '#3E8EF7', '#2BB673', '#B36BFF', '#F2B705', '#E5487A'];
const POSITIONS: { value: CaptionPosition; label: string }[] = [
  { value: 'upper_third', label: 'Top' },
  { value: 'middle', label: 'Middle' },
  { value: 'lower_middle', label: 'Lower' },
];

export default function PlanScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) });
  if (q.isPending) return <Loading />;
  if (q.isError) return <Message title="Couldn't load this reel" body={q.error.message} />;
  if (!q.data.plan) return <Message title="No edit plan yet" body="Go back and tap Edit my reel first." />;
  return <PlanEditor project={q.data} />;
}

function PlanEditor({ project }: { project: Project }) {
  const t = useTheme();
  const qc = useQueryClient();
  // unsaved edits only; null = showing the server's plan as it is
  const [local, setLocal] = useState<EditPlan | null>(null);
  const draft = local ?? project.plan!;
  const dirty = local !== null;

  const clipsByAlias = useMemo(() => {
    const m: Record<string, Clip> = {};
    project.clips.forEach((c, i) => (m[`C${i + 1}`] = c));
    return m;
  }, [project.clips]);
  const tl = timeline(draft);

  const edit = (fn: (p: EditPlan) => EditPlan) => setLocal((cur) => fn(structuredClone(cur ?? project.plan!)));

  const save = useMutation({
    mutationFn: () => api.savePlan(project.id, draft),
    onSuccess: (p) => {
      qc.setQueryData(['project', project.id], p);
      setLocal(null);
    },
  });

  return (
    <>
      <Stack.Screen options={{ title: 'Edit plan' }} />
      <Screen title={`${fmt(tl.total)} reel`} subtitle={draft.summary} right={<StatusChip status={project.status} />}>
        <BriefEditor project={project} planDirty={dirty} />
        <TimelineBar draft={draft} total={tl.total} tail={tl.tail} />
        <UnusedClips clips={project.clips} draft={draft} onAdd={(alias) => edit((p) => { p.shots.push(newShot(alias, clipsByAlias[alias])); return p; })} />

        {!dirty && project.plan_warnings.length ? (
          <Card>
            <Text style={{ color: t.text, fontWeight: '600' }}>Fixed automatically</Text>
            {project.plan_warnings.map((w) => <Text key={w} style={{ color: t.textSecondary, fontSize: 13 }}>• {w}</Text>)}
          </Card>
        ) : null}

        <SectionTitle>Shots · {draft.shots.length}</SectionTitle>
        {draft.shots.map((s, i) => (
          <ShotRow key={i} i={i} draft={draft} clip={clipsByAlias[s.clip]} start={tl.shots[i]?.start ?? 0} edit={edit} />
        ))}
        <AddShot clips={project.clips} onAdd={(alias) => edit((p) => { p.shots.push(newShot(alias, clipsByAlias[alias])); return p; })} />

        <SectionTitle>Captions · {draft.captions.length}</SectionTitle>
        {draft.captions.map((c, i) => (
          <CaptionRow key={i} c={c} i={i} total={tl.total} edit={edit} />
        ))}
        <Button label="+ Add caption" kind="secondary" onPress={() => edit((p) => {
          const last = p.captions.at(-1);
          const start = Math.min(round(last ? last.end_s + 0.3 : 0.3), Math.max(0, tl.total - 1.5));
          p.captions.push({ text: 'New caption', start_s: start, end_s: Math.min(tl.total, start + 2), position: 'lower_middle', highlight: null });
          return p;
        })} />

        <SectionTitle>Effects · {(draft.effects ?? []).length}</SectionTitle>
        {(draft.effects ?? []).map((e, i) => (
          <EffectRow key={i} e={e} i={i} total={tl.footage} edit={edit} />
        ))}
        <AddEffect onAdd={(type) => edit((p) => {
          const list = (p.effects ??= []);
          const last = list.at(-1);
          const len = EFFECTS[type].len;
          const start = round(Math.min(last ? last.end_s + 1 : 1, Math.max(0, tl.footage - len)), 0.05);
          list.push({ type, start_s: start, end_s: round(Math.min(tl.footage, start + len), 0.05),
            text: type === 'freeze_frame' ? 'Look here' : null, look: type === 'grade' ? 'moody' : null });
          list.sort((a, b) => a.start_s - b.start_s);
          return p;
        })} />

        {draft.overlays.length ? <SectionTitle>Cards</SectionTitle> : null}
        {draft.overlays.map((o, i) => (
          <Card key={i}>
            <View style={styles.rowBetween}>
              <Text style={{ color: t.text, fontWeight: '600' }}>{o.type === 'stats_card' ? 'Stats card' : 'Title'} · {fmt(o.start_s)}–{fmt(o.end_s)}</Text>
              <Button label="Remove" kind="ghost" style={styles.small} onPress={() => edit((p) => { p.overlays.splice(i, 1); return p; })} />
            </View>
            {o.title ? <Text style={{ color: t.textSecondary }}>{o.title}</Text> : null}
            {o.items.length ? <Text style={{ color: t.accent, fontWeight: '600' }}>{o.items.map((x) => x.value).join('  ·  ')}</Text> : null}
          </Card>
        ))}

        {save.isError ? <Text style={{ color: t.danger }}>{save.error.message}</Text> : null}
        {dirty ? (
          <View style={styles.row}>
            <Button label="Undo changes" kind="secondary" style={{ flex: 1 }} onPress={() => setLocal(null)} />
            <Button label="Save changes" style={{ flex: 1 }} loading={save.isPending} onPress={() => save.mutate()} />
          </View>
        ) : (
          <RenderPanel project={project} />
        )}
      </Screen>
    </>
  );
}

// brief: title, script, stats - editable, then re-plan -----------------------------

function BriefEditor({ project, planDirty }: { project: Project; planDirty: boolean }) {
  const t = useTheme();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
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
      router.back(); // the reel screen shows "Editing your reel…" and the new plan when it's ready
    },
  });

  if (!open) {
    return (
      <Card onPress={() => setOpen(true)}>
        <View style={styles.rowBetween}>
          <Text style={{ color: t.text, fontWeight: '600', flex: 1 }} numberOfLines={1}>{project.title}</Text>
          <Text style={{ color: t.accent, fontWeight: '600' }}>Edit details</Text>
        </View>
        {project.script ? <Text style={{ color: t.textSecondary }} numberOfLines={2}>{project.script}</Text> : null}
      </Card>
    );
  }
  return (
    <Card>
      <Field label="Title" value={title} onChangeText={setTitle} maxLength={200} />
      <Field label="Script or story" value={script} onChangeText={setScript} multiline maxLength={4000}
        placeholder="Clip order, the lines to show, what to highlight…" />
      <VoiceButton language={project.language} label="Speak your script" onText={(x) => setScript((s) => (s.trim() ? `${s.trim()}\n${x}` : x))} />
      <SectionTitle>Stats for the end card</SectionTitle>
      {stats.map((s, i) => (
        <View key={i} style={styles.row}>
          <View style={{ flex: 1 }}>
            <Field value={s.label} placeholder="Label" maxLength={40} onChangeText={(v) => setStats((r) => r.map((x, j) => (j === i ? { ...x, label: v } : x)))} />
          </View>
          <View style={{ flex: 1.3 }}>
            <Field value={s.value} placeholder="Value" maxLength={40} onChangeText={(v) => setStats((r) => r.map((x, j) => (j === i ? { ...x, value: v } : x)))} />
          </View>
        </View>
      ))}
      {save.isError ? <Text style={{ color: t.danger }}>{save.error.message}</Text> : null}
      {confirming ? (
        <ConfirmAI
          title="Write a new plan from these details?"
          note={planDirty ? 'Your unsaved plan edits will be replaced.' : 'The current plan will be replaced.'}
          confirmLabel="Re-plan"
          onConfirm={() => replan.mutate()}
          onCancel={() => setConfirming(false)}
          loading={replan.isPending}
          error={replan.isError ? replan.error.message : null}
        />
      ) : (
        <>
          <View style={styles.row}>
            <Button label="Close" kind="secondary" style={{ flex: 1 }} onPress={() => setOpen(false)} />
            <Button label="Save details" kind="secondary" style={{ flex: 1 }} disabled={!changed} loading={save.isPending} onPress={() => save.mutate()} />
          </View>
          <Button label="Re-plan with these details" onPress={() => setConfirming(true)} />
          <Text style={{ color: t.textSecondary, fontSize: 12 }}>Saving details is free. Re-planning uses 1 AI edit and uses all your clips.</Text>
        </>
      )}
    </Card>
  );
}

// clips not in the plan, and adding shots -------------------------------------------

/** A new shot from a whole clip (up to 6 s), placed at the end; trim it with the nudges. */
function newShot(alias: string, clip?: Clip): Shot {
  const len = clip?.duration_s ?? 3;
  return { clip: alias, in_s: 0, out_s: Math.min(len, 6), speed: 1, zoom_from: 1, zoom_to: 1, focus_x: 0.5, focus_y: 0.5, keep_audio: !!clip?.has_speech, purpose: 'added by you' };
}

function UnusedClips({ clips, draft, onAdd }: { clips: Clip[]; draft: EditPlan; onAdd: (alias: string) => void }) {
  const t = useTheme();
  const used = new Set(draft.shots.map((s) => s.clip));
  const unused = clips.map((c, i) => ({ c, alias: `C${i + 1}` })).filter(({ alias, c }) => !used.has(alias) && c.status === 'ready');
  if (!unused.length) return null;
  return (
    <Card style={{ borderColor: t.accent }}>
      <Text style={{ color: t.text, fontWeight: '600' }}>
        {unused.length} clip{unused.length === 1 ? '' : 's'} not in this edit
      </Text>
      {unused.map(({ c, alias }) => (
        <View key={alias} style={styles.shot}>
          <View style={[styles.thumbSmall, { backgroundColor: t.backgroundSelected }]}>
            {c.thumbnail_url ? <Image source={{ uri: c.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
          </View>
          <Text style={{ color: t.textSecondary, flex: 1 }}>{alias} · {formatSeconds(c.duration_s ?? 0)}</Text>
          <Button label="Add" kind="ghost" style={styles.small} onPress={() => onAdd(alias)} />
        </View>
      ))}
    </Card>
  );
}

function AddShot({ clips, onAdd }: { clips: Clip[]; onAdd: (alias: string) => void }) {
  const t = useTheme();
  const [open, setOpen] = useState(false);
  if (!open) return <Button label="+ Add shot" kind="secondary" onPress={() => setOpen(true)} />;
  return (
    <Card>
      <Text style={{ color: t.text, fontWeight: '600' }}>Add a shot from</Text>
      <View style={styles.pickRow}>
        {clips.map((c, i) => c.status === 'ready' ? (
          <Pressable key={c.id} onPress={() => { onAdd(`C${i + 1}`); setOpen(false); }} style={{ alignItems: 'center', gap: 2 }}>
            <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]}>
              {c.thumbnail_url ? <Image source={{ uri: c.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
            </View>
            <Text style={{ color: t.textSecondary, fontSize: 12 }}>C{i + 1}</Text>
          </Pressable>
        ) : null)}
      </View>
      <Button label="Cancel" kind="ghost" onPress={() => setOpen(false)} />
    </Card>
  );
}

// timeline -------------------------------------------------------------------------

function TimelineBar({ draft, total, tail }: { draft: EditPlan; total: number; tail: number }) {
  const t = useTheme();
  if (!total) return null;
  return (
    <View style={{ gap: Spacing.one }}>
      <View style={[styles.bar, { backgroundColor: t.backgroundSelected }]}>
        {draft.shots.map((s, i) => (
          <View key={i} style={{ flex: shotLength(s), backgroundColor: SHOT_COLORS[i % SHOT_COLORS.length], justifyContent: 'center' }}>
            <Text style={styles.barLabel} numberOfLines={1}>{s.clip}</Text>
          </View>
        ))}
        {tail ? <View style={{ flex: tail, backgroundColor: t.border }} /> : null}
      </View>
      <View style={[styles.capBar]}>
        {draft.captions.map((c, i) => (
          <View key={i} style={[styles.capTick, { left: `${(c.start_s / total) * 100}%`, width: `${((c.end_s - c.start_s) / total) * 100}%`, backgroundColor: t.text }]} />
        ))}
      </View>
      <Text style={{ color: t.textSecondary, fontSize: 12 }}>Shots on top, captions below{tail ? ` · last frame held ${tail.toFixed(1)}s under the card` : ''}</Text>
    </View>
  );
}

// shots ----------------------------------------------------------------------------

function ShotRow({ i, draft, clip, start, edit }: {
  i: number; draft: EditPlan; clip?: Clip; start: number; edit: (fn: (p: EditPlan) => EditPlan) => void;
}) {
  const t = useTheme();
  const s = draft.shots[i];
  const len = shotLength(s);
  const clipLen = clip?.duration_s ?? s.out_s;
  const nudge = (key: 'in_s' | 'out_s', d: number) => edit((p) => {
    const sh = p.shots[i];
    const v = round(sh[key] + d);
    if (key === 'in_s') sh.in_s = Math.max(0, Math.min(v, sh.out_s - 0.5));
    else sh.out_s = Math.min(clipLen, Math.max(v, sh.in_s + 0.5));
    return p;
  });
  return (
    <Card style={styles.shot}>
      <View style={[styles.swatch, { backgroundColor: SHOT_COLORS[i % SHOT_COLORS.length] }]} />
      <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]}>
        {clip?.thumbnail_url ? <Image source={{ uri: clip.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ color: t.text, fontWeight: '600' }}>
          {fmt(start)} · {s.clip} · {len.toFixed(1)}s{s.speed !== 1 ? ` · ${s.speed}×` : ''}
          {Math.max(s.zoom_from, s.zoom_to) > 1.05 ? ' · zoom' : ''}
        </Text>
        <Text style={{ color: t.textSecondary, fontSize: 13 }} numberOfLines={2}>{s.purpose}</Text>
        <View style={styles.nudges}>
          <Nudge label="start −" onPress={() => nudge('in_s', -0.5)} />
          <Nudge label="start +" onPress={() => nudge('in_s', 0.5)} />
          <Nudge label="end −" onPress={() => nudge('out_s', -0.5)} />
          <Nudge label="end +" onPress={() => nudge('out_s', 0.5)} />
        </View>
        <Text style={{ color: t.textSecondary, fontSize: 12 }}>Uses {s.in_s.toFixed(1)}–{s.out_s.toFixed(1)}s of {formatSeconds(clipLen)}</Text>
      </View>
      <View style={{ gap: Spacing.one, alignItems: 'flex-end' }}>
        <View style={styles.row}>
          <Nudge label="↑" onPress={() => i > 0 && edit((p) => { [p.shots[i - 1], p.shots[i]] = [p.shots[i], p.shots[i - 1]]; return p; })} />
          <Nudge label="↓" onPress={() => i < draft.shots.length - 1 && edit((p) => { [p.shots[i + 1], p.shots[i]] = [p.shots[i], p.shots[i + 1]]; return p; })} />
        </View>
        <Pressable onPress={() => edit((p) => { p.shots[i].keep_audio = !p.shots[i].keep_audio; return p; })}
          accessibilityRole="switch" accessibilityState={{ checked: s.keep_audio }}
          style={[styles.toggle, { borderColor: s.keep_audio ? t.accent : t.border }]}>
          <Text style={{ color: s.keep_audio ? t.accent : t.textSecondary, fontSize: 12, fontWeight: '600' }}>{s.keep_audio ? 'Sound on' : 'Muted'}</Text>
        </Pressable>
        {draft.shots.length > 1 ? (
          <Button label="Remove" kind="ghost" style={styles.small} onPress={() => edit((p) => { p.shots.splice(i, 1); return p; })} />
        ) : null}
      </View>
    </Card>
  );
}

function Nudge({ label, onPress }: { label: string; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} style={[styles.nudge, { borderColor: t.border }]}>
      <Text style={{ color: t.text, fontSize: 12 }}>{label}</Text>
    </Pressable>
  );
}

// captions -------------------------------------------------------------------------

function CaptionRow({ c, i, total, edit }: { c: Caption; i: number; total: number; edit: (fn: (p: EditPlan) => EditPlan) => void }) {
  const t = useTheme();
  const shortBy = readableSeconds(c.text) - (c.end_s - c.start_s);
  const shift = (key: 'start_s' | 'end_s', d: number) => edit((p) => {
    const cap = p.captions[i];
    const v = round(cap[key] + d, 0.05); // 0.05 grid so 0.25 s steps stay exact
    if (key === 'start_s') cap.start_s = Math.max(0, Math.min(v, cap.end_s - 0.5));
    else cap.end_s = Math.min(total, Math.max(v, cap.start_s + 0.5));
    return p;
  });
  return (
    <Card>
      <TextInput
        value={c.text}
        onChangeText={(text) => edit((p) => { p.captions[i].text = text; return p; })}
        style={[styles.capInput, { color: t.text, borderColor: t.border, backgroundColor: t.background }]}
        multiline
        maxLength={140}
      />
      <View style={styles.rowBetween}>
        <Text style={{ color: t.textSecondary, fontSize: 13 }}>
          {fmt(c.start_s)} – {fmt(c.end_s)}{c.highlight ? ` · orange: “${c.highlight}”` : ''}
        </Text>
        <Button label="Delete" kind="ghost" style={styles.small} onPress={() => edit((p) => { p.captions.splice(i, 1); return p; })} />
      </View>
      <View style={styles.nudges}>
        <Nudge label="◀ start" onPress={() => shift('start_s', -0.25)} />
        <Nudge label="start ▶" onPress={() => shift('start_s', 0.25)} />
        <Nudge label="◀ end" onPress={() => shift('end_s', -0.25)} />
        <Nudge label="end ▶" onPress={() => shift('end_s', 0.25)} />
      </View>
      {shortBy > 0.05 ? (
        <Text style={{ color: t.accent, fontSize: 12 }}>On screen {(c.end_s - c.start_s).toFixed(1)}s - needs about {readableSeconds(c.text).toFixed(1)}s to read</Text>
      ) : null}
      <View style={styles.choices}>
        {POSITIONS.map((pos) => (
          <Choice key={pos.value} label={pos.label} selected={c.position === pos.value}
            onPress={() => edit((p) => { p.captions[i].position = pos.value; return p; })} />
        ))}
      </View>
    </Card>
  );
}

// effects ----------------------------------------------------------------------------

const EFFECTS: Record<EffectType, { label: string; hint: string; len: number }> = {
  punch_in: { label: 'Punch in', hint: 'Quick zoom onto your face', len: 1 },
  slow_push: { label: 'Slow push', hint: 'Slow cinematic push in', len: 3 },
  spotlight: { label: 'Spotlight', hint: 'Everything but you goes dark', len: 2 },
  grade: { label: 'Colour look', hint: 'A mood for this stretch', len: 4 },
  freeze_frame: { label: 'Freeze frame', hint: 'Picture holds, a label points at you', len: 1.5 },
  flash: { label: 'Flash', hint: 'White flash on a beat', len: 0.3 },
  countdown: { label: 'Countdown', hint: 'Big 3-2-1 above you', len: 2 },
};
const LOOKS: { value: Look; label: string }[] = [
  { value: 'moody', label: 'Moody' }, { value: 'bw', label: 'B&W' }, { value: 'warm', label: 'Warm' },
  { value: 'cool', label: 'Cool' }, { value: 'pop', label: 'Pop' },
];

function EffectRow({ e, i, total, edit }: { e: Effect; i: number; total: number; edit: (fn: (p: EditPlan) => EditPlan) => void }) {
  const t = useTheme();
  const info = EFFECTS[e.type] ?? { label: e.type, hint: '', len: 1 };
  const change = (fn: (x: Effect) => void) => edit((p) => { fn(p.effects![i]); p.effects!.sort((a, b) => a.start_s - b.start_s); return p; });
  const move = (d: number) => change((x) => {
    const len = x.end_s - x.start_s;
    x.start_s = round(Math.max(0, Math.min(x.start_s + d, total - len)), 0.05);
    x.end_s = round(x.start_s + len, 0.05);
  });
  const stretch = (d: number) => change((x) => { x.end_s = round(Math.min(total, Math.max(x.start_s + 0.1, x.end_s + d)), 0.05); });
  return (
    <Card>
      <View style={styles.rowBetween}>
        <View style={{ flex: 1 }}>
          <Text style={{ color: t.text, fontWeight: '600' }}>{info.label} · {fmt(e.start_s)}–{fmt(e.end_s)}</Text>
          <Text style={{ color: t.textSecondary, fontSize: 13 }}>{info.hint}</Text>
        </View>
        <Button label="Delete" kind="ghost" style={styles.small} onPress={() => edit((p) => { p.effects!.splice(i, 1); return p; })} />
      </View>
      {e.type === 'freeze_frame' ? (
        <TextInput
          value={e.text ?? ''}
          placeholder="Label, e.g. That's me"
          placeholderTextColor={t.textSecondary}
          onChangeText={(text) => edit((p) => { p.effects![i].text = text; return p; })}
          style={[styles.capInput, { color: t.text, borderColor: t.border, backgroundColor: t.background }]}
          maxLength={40}
        />
      ) : null}
      {e.type === 'grade' ? (
        <View style={styles.choices}>
          {LOOKS.map((l) => (
            <Choice key={l.value} label={l.label} selected={(e.look ?? 'moody') === l.value} onPress={() => change((x) => { x.look = l.value; })} />
          ))}
        </View>
      ) : null}
      <View style={styles.nudges}>
        <Nudge label="◀ earlier" onPress={() => move(-0.25)} />
        <Nudge label="later ▶" onPress={() => move(0.25)} />
        <Nudge label="shorter" onPress={() => stretch(-0.25)} />
        <Nudge label="longer" onPress={() => stretch(0.25)} />
      </View>
    </Card>
  );
}

function AddEffect({ onAdd }: { onAdd: (type: EffectType) => void }) {
  const t = useTheme();
  const [open, setOpen] = useState(false);
  if (!open) return <Button label="+ Add effect" kind="secondary" onPress={() => setOpen(true)} />;
  return (
    <Card>
      <Text style={{ color: t.text, fontWeight: '600' }}>Add an effect</Text>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>Zooms, spotlight, freeze and countdown follow your face.</Text>
      <View style={styles.choices}>
        {(Object.keys(EFFECTS) as EffectType[]).map((k) => (
          <Choice key={k} label={EFFECTS[k].label} selected={false} onPress={() => { onAdd(k); setOpen(false); }} />
        ))}
      </View>
      <Button label="Cancel" kind="ghost" style={styles.small} onPress={() => setOpen(false)} />
    </Card>
  );
}

// render -----------------------------------------------------------------------------

function RenderPanel({ project }: { project: Project }) {
  const t = useTheme();
  const qc = useQueryClient();
  const renders = useQuery({
    queryKey: ['renders', project.id],
    queryFn: () => api.renders(project.id),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'pending' || r.status === 'processing') ? 1500 : false),
  });
  const start = useMutation({
    mutationFn: (quality: 'preview' | 'final') => api.render(project.id, quality),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['renders', project.id] });
      qc.invalidateQueries({ queryKey: ['project', project.id] });
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
  const busy = renders.data?.some((r) => r.status === 'pending' || r.status === 'processing') || project.status === 'rendering';

  return (
    <View style={{ gap: Spacing.two, marginTop: Spacing.two }}>
      <Text style={{ color: t.textSecondary, fontSize: 14 }}>Rendering is free and never replaces an earlier version.</Text>
      <View style={styles.row}>
        <Button label="Quick preview" kind="secondary" style={{ flex: 1 }} disabled={busy} loading={start.isPending && start.variables === 'preview'} onPress={() => start.mutate('preview')} />
        <Button label="Render final" style={{ flex: 1 }} disabled={busy} loading={start.isPending && start.variables === 'final'} onPress={() => start.mutate('final')} />
      </View>
      {start.isError ? <Text style={{ color: t.danger }}>{start.error.message}</Text> : null}
      {(renders.data ?? []).map((r) => <RenderRow key={r.id} r={r} projectId={project.id} />)}
    </View>
  );
}

function RenderRow({ r, projectId }: { r: Render; projectId: string }) {
  const t = useTheme();
  const status = r.status === 'ready' ? `${formatSeconds(r.duration_s ?? 0)} · ${((r.size_bytes ?? 0) / 1e6).toFixed(1)} MB · made in ${Math.round(r.seconds_taken ?? 0)}s`
    : r.status === 'failed' ? (r.error ?? 'Failed') : r.status === 'pending' ? 'Waiting to start…' : null;
  return (
    <Card style={styles.shot}>
      <View style={[styles.thumb, { backgroundColor: t.backgroundSelected }]}>
        {r.thumbnail_url ? <Image source={{ uri: r.thumbnail_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ color: t.text, fontWeight: '600' }}>v{r.version} · {r.quality === 'final' ? 'Final' : 'Preview'}</Text>
        {status ? <Text style={{ color: r.status === 'failed' ? t.danger : t.textSecondary, fontSize: 13 }}>{status}</Text> : null}
        {r.status === 'processing' ? <ProgressBar value={r.progress ?? 0} label={r.stage ?? 'Rendering'} /> : null}
        {r.status === 'ready' && r.checks?.length ? (
          <Text style={{ fontSize: 12, color: t.textSecondary }}>
            {r.checks.map((c) => (
              <Text key={c.name} style={{ color: c.ok ? t.success : t.danger }}>{c.ok ? '✓' : '✗'} {c.name}{c.ok ? '' : ` (${c.detail})`}{'   '}</Text>
            ))}
          </Text>
        ) : null}
        {r.status === 'ready' && r.notes?.length ? (
          <Text style={{ fontSize: 12, color: t.textSecondary }}>{r.notes.join(' · ')}</Text>
        ) : null}
      </View>
      {r.status === 'ready' ? (
        <Button label="Watch" kind="ghost" style={styles.small}
          onPress={() => router.push({ pathname: '/reel/watch/[renderId]', params: { renderId: r.id, projectId } })} />
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: Spacing.two },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.two },
  bar: { flexDirection: 'row', height: 28, borderRadius: Radius.sm, overflow: 'hidden', gap: 2 },
  barLabel: { color: '#fff', fontSize: 11, fontWeight: '700', textAlign: 'center' },
  capBar: { height: 6, position: 'relative' },
  capTick: { position: 'absolute', top: 0, height: 6, borderRadius: 3, opacity: 0.7 },
  shot: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, padding: Spacing.two },
  swatch: { width: 4, alignSelf: 'stretch', borderRadius: 2 },
  thumb: { width: 54, height: 96, borderRadius: Radius.sm, overflow: 'hidden' },
  thumbSmall: { width: 36, height: 64, borderRadius: Radius.sm, overflow: 'hidden' },
  pickRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  nudges: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.one, marginTop: Spacing.one },
  nudge: { borderWidth: 1, borderRadius: Radius.sm, paddingHorizontal: Spacing.two, paddingVertical: 4 },
  toggle: { borderWidth: 1, borderRadius: Radius.pill, paddingHorizontal: Spacing.two, paddingVertical: 4 },
  small: { minHeight: 32, paddingHorizontal: Spacing.two },
  capInput: { borderWidth: 1, borderRadius: Radius.md, padding: Spacing.two, fontSize: 16, minHeight: 44 },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
});
