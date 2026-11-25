/**
 * The timeline, like a phone video editor: the playhead stays in the middle and the tracks scroll
 * under it (scrolling = scrubbing). Tracks: video parts, captions, effects, sounds.
 *
 * Tap a block to select it. A selected block can be dragged (parts: to reorder; captions and
 * effects: to move in time) and has handles on both edges to trim it.
 * Dragging uses React Native's PanResponder: same on Android, iOS and web, nothing native to install.
 */

import { Image } from 'expo-image';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { type GestureResponderHandlers, type LayoutChangeEvent, PanResponder, Pressable, ScrollView, type ScrollViewInstance, StyleSheet, Text, View } from 'react-native';

import { Radius } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { shotLength } from '@/lib/plan';
import type { SoundCue } from '@/lib/sfx-cues';
import type { Clip, EditPlan } from '@/lib/types';

export type Sel = { kind: 'part' | 'caption' | 'effect' | 'cue'; i: number } | null;
export type DragKind = 'move' | 'start' | 'end';
export type DragPhase = 'begin' | 'move' | 'end';

export const PART_COLORS = ['#FF5A1F', '#3E8EF7', '#2BB673', '#B36BFF', '#F2B705', '#E5487A'];
const FX_ICON: Record<string, string> = {
  punch_in: '🔍', slow_push: '🎥', spotlight: '🔦', grade: '🎨', freeze_frame: '⏸️', flash: '⚡', countdown: '3️⃣', backdrop_word: '🅰️',
};
const FX_NAME: Record<string, string> = {
  punch_in: 'Punch in', slow_push: 'Slow push', spotlight: 'Spotlight', grade: 'Look', freeze_frame: 'Freeze', flash: 'Flash', countdown: '3-2-1', backdrop_word: 'Word',
};
const LANE = { ruler: 18, part: 54, caption: 30, effect: 26, sound: 24 };
const LABEL_W = 28;

export function Timeline({ plan, clips, starts, total, time, pps, sel, playing, cues, onSeek, onSelect, onDrag, onReorder }: {
  plan: EditPlan;
  clips: Record<string, Clip>;
  starts: number[];
  total: number;
  time: number;
  pps: number; // pixels per second (zoom)
  sel: Sel;
  playing: boolean;
  cues: SoundCue[];
  onSeek: (t: number) => void;
  onSelect: (s: Sel) => void;
  onDrag: (target: { kind: 'part' | 'caption' | 'effect'; i: number }, how: DragKind, phase: DragPhase, dtSeconds: number) => void;
  onReorder: (from: number, to: number) => void;
}) {
  const t = useTheme();
  const scroll = useRef<ScrollViewInstance>(null);
  const [w, setW] = useState(0);
  const [dragging, setDragging] = useState(false);
  const progX = useRef(-1); // where we last scrolled to ourselves; anything else is the user scrubbing
  const pad = Math.max(0, (w - LABEL_W) / 2);
  const width = total * pps;

  // follow the playhead (playing, or a seek from elsewhere)
  useEffect(() => {
    const x = Math.round(time * pps);
    if (Math.abs(x - progX.current) < 1) return;
    progX.current = x;
    scroll.current?.scrollTo({ x, animated: false });
  }, [time, pps]);

  const onScroll = (x: number) => {
    if (Math.abs(x - progX.current) <= 1) return;
    progX.current = x;
    if (!playing) onSeek(Math.max(0, Math.min(total, x / pps)));
  };

  // effects that overlap go on a second row
  const fxRows = useMemo(() => {
    const ends: number[] = [];
    return (plan.effects ?? []).map((e) => {
      let r = ends.findIndex((end) => end <= e.start_s + 0.01);
      if (r < 0) { r = ends.length; ends.push(0); }
      ends[r] = e.end_s;
      return r;
    });
  }, [plan.effects]);
  const fxRowCount = Math.max(1, ...fxRows.map((r) => r + 1));

  const dragFor = (kind: 'part' | 'caption' | 'effect', i: number) => (how: DragKind, phase: DragPhase, dx: number) => {
    if (phase === 'begin') setDragging(true);
    if (phase === 'end') setDragging(false);
    onDrag({ kind, i }, how, phase, dx / pps);
  };

  const step = pps >= 60 ? 1 : pps >= 30 ? 2 : 5;
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, k) => k * step);

  return (
    <View style={styles.wrap} onLayout={(e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width)}>
      <View style={[styles.labels, { borderColor: t.border }]}>
        <View style={{ height: LANE.ruler }} />
        <Text style={[styles.label, { height: LANE.part, lineHeight: LANE.part }]}>🎬</Text>
        <Text style={[styles.label, { height: LANE.caption, lineHeight: LANE.caption }]}>💬</Text>
        <Text style={[styles.label, { height: LANE.effect * fxRowCount, lineHeight: LANE.effect * fxRowCount }]}>✨</Text>
        <Text style={[styles.label, { height: LANE.sound, lineHeight: LANE.sound }]}>🔊</Text>
      </View>
      <ScrollView
        ref={scroll}
        horizontal
        scrollEnabled={!dragging}
        showsHorizontalScrollIndicator={false}
        scrollEventThrottle={16}
        onScroll={(e) => onScroll(e.nativeEvent.contentOffset.x)}
        contentContainerStyle={{ paddingHorizontal: pad }}>
        <Pressable onPress={() => onSelect(null)} style={{ width }}>
          {/* ruler */}
          <View style={{ height: LANE.ruler }}>
            {ticks.map((s) => (
              <Text key={s} style={[styles.tick, { left: s * pps, color: t.textSecondary }]}>{s % (step * 2) === 0 ? `${s}s` : '·'}</Text>
            ))}
          </View>
          {/* parts */}
          <View style={{ height: LANE.part }}>
            {plan.shots.map((s, i) => (
              <PartBlock key={i} i={i} x={(starts[i] ?? 0) * pps} w={shotLength(s) * pps} clip={clips[s.clip]} muted={!s.keep_audio}
                selected={sel?.kind === 'part' && sel.i === i} onSelect={() => onSelect({ kind: 'part', i })}
                onDrag={dragFor('part', i)}
                onDrop={(dx) => {
                  const center = (starts[i] ?? 0) * pps + (shotLength(s) * pps) / 2 + dx;
                  const to = plan.shots.filter((o, j) => j !== i && (starts[j] ?? 0) * pps + (shotLength(o) * pps) / 2 < center).length;
                  if (to !== i) onReorder(i, to);
                }} />
            ))}
          </View>
          {/* captions */}
          <View style={{ height: LANE.caption }}>
            {plan.captions.map((c, i) => (
              <Block key={i} x={c.start_s * pps} w={(c.end_s - c.start_s) * pps} top={3} h={LANE.caption - 6}
                color={t.text} fg={t.background} selected={sel?.kind === 'caption' && sel.i === i}
                onSelect={() => onSelect({ kind: 'caption', i })} onDrag={dragFor('caption', i)} label={c.text} />
            ))}
          </View>
          {/* effects */}
          <View style={{ height: LANE.effect * fxRowCount }}>
            {(plan.effects ?? []).map((e, i) => (
              <Block key={i} x={e.start_s * pps} w={Math.max(0.1, e.end_s - e.start_s) * pps} top={fxRows[i] * LANE.effect + 2} h={LANE.effect - 4}
                color={t.accent} fg="#fff" selected={sel?.kind === 'effect' && sel.i === i}
                onSelect={() => onSelect({ kind: 'effect', i })} onDrag={dragFor('effect', i)}
                label={`${FX_ICON[e.type] ?? '✨'} ${e.text || FX_NAME[e.type] || e.type}`} />
            ))}
          </View>
          {/* sounds: where each sound effect plays */}
          <View style={{ height: LANE.sound }}>
            {cues.map((c, i) => (
              <Pressable key={i} onPress={() => onSelect({ kind: 'cue', i })} hitSlop={4}
                style={[styles.cue, { left: c.at * pps - 10, borderColor: sel?.kind === 'cue' && sel.i === i ? t.accent : 'transparent' }]}>
                <Text style={{ fontSize: 13 }}>{c.icon}</Text>
              </Pressable>
            ))}
          </View>
        </Pressable>
      </ScrollView>
      {/* the playhead */}
      <View pointerEvents="none" style={[styles.playhead, { left: LABEL_W + pad - 1, backgroundColor: t.text }]} />
    </View>
  );
}

/** A drag that only a selected block answers, so an unselected one never fights the scroll. */
function useDrag(enabled: boolean, cb: (phase: DragPhase, dx: number) => void, onTap?: () => void): GestureResponderHandlers {
  const latest = useRef({ enabled, cb, onTap });
  useLayoutEffect(() => {
    latest.current = { enabled, cb, onTap };
  });
  // the handlers only read the ref when a touch happens, never during render
  // eslint-disable-next-line react-hooks/refs
  const [responder] = useState(() => PanResponder.create({
    onStartShouldSetPanResponder: () => latest.current.enabled,
    onMoveShouldSetPanResponderCapture: (_, g) => latest.current.enabled && Math.abs(g.dx) > 2,
    onPanResponderTerminationRequest: () => false,
    onPanResponderGrant: () => latest.current.cb('begin', 0),
    onPanResponderMove: (_, g) => latest.current.cb('move', g.dx),
    onPanResponderRelease: (_, g) => {
      latest.current.cb('end', g.dx);
      if (Math.abs(g.dx) < 3) latest.current.onTap?.();
    },
    onPanResponderTerminate: (_, g) => latest.current.cb('end', g.dx),
  }));
  return responder.panHandlers;
}

function Handle({ side, onDrag }: { side: 'left' | 'right'; onDrag: (phase: DragPhase, dx: number) => void }) {
  const handlers = useDrag(true, onDrag);
  return (
    <View {...handlers} style={[styles.handle, side === 'left' ? { left: -9 } : { right: -9 }]}>
      <View style={styles.grip} />
    </View>
  );
}

function Block({ x, w, top, h, color, fg, selected, label, onSelect, onDrag }: {
  x: number; w: number; top: number; h: number; color: string; fg: string; selected: boolean; label: string;
  onSelect: () => void; onDrag: (how: DragKind, phase: DragPhase, dx: number) => void;
}) {
  const t = useTheme();
  const body = useDrag(selected, (phase, dx) => onDrag('move', phase, dx));
  const inner = (
    <Text numberOfLines={1} style={[styles.blockText, { color: fg }]}>{label}</Text>
  );
  const style = [styles.block, { left: x, width: Math.max(6, w), top, height: h, backgroundColor: color, opacity: selected ? 1 : 0.8, borderColor: selected ? t.accent : 'transparent' }];
  if (!selected) return <Pressable onPress={onSelect} style={style}>{inner}</Pressable>;
  return (
    <View {...body} style={[style, styles.selected]}>
      {inner}
      <Handle side="left" onDrag={(phase, dx) => onDrag('start', phase, dx)} />
      <Handle side="right" onDrag={(phase, dx) => onDrag('end', phase, dx)} />
    </View>
  );
}

function PartBlock({ i, x, w, clip, muted, selected, onSelect, onDrag, onDrop }: {
  i: number; x: number; w: number; clip?: Clip; muted: boolean; selected: boolean;
  onSelect: () => void; onDrag: (how: DragKind, phase: DragPhase, dx: number) => void; onDrop: (dx: number) => void;
}) {
  const t = useTheme();
  const [dx, setDx] = useState(0);
  const color = PART_COLORS[i % PART_COLORS.length];
  const body = useDrag(selected, (phase, d) => {
    onDrag('move', phase, 0); // tells the timeline a drag is on (so it doesn't scroll); the reorder happens on drop
    if (phase === 'end') {
      setDx(0);
      onDrop(d);
    } else setDx(d);
  });
  const content = (
    <>
      {clip?.thumbnail_url ? <Image source={{ uri: clip.thumbnail_url }} style={styles.partImg} contentFit="cover" /> : null}
      <View style={[styles.partNum, { backgroundColor: color }]}><Text style={styles.partNumText}>{i + 1}</Text></View>
      {muted ? <Text style={styles.mute}>🔇</Text> : null}
    </>
  );
  const style = [styles.part, { left: x + 1, width: Math.max(8, w - 2), borderColor: selected ? '#fff' : color, backgroundColor: t.backgroundSelected }];
  if (!selected) return <Pressable onPress={onSelect} style={style}>{content}</Pressable>;
  return (
    <View {...body} style={[style, styles.selected, { transform: [{ translateX: dx }], zIndex: 5, opacity: dx ? 0.85 : 1 }]}>
      {content}
      <Handle side="left" onDrag={(phase, d) => onDrag('start', phase, d)} />
      <Handle side="right" onDrag={(phase, d) => onDrag('end', phase, d)} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: 'row', position: 'relative' },
  labels: { width: LABEL_W, borderRightWidth: StyleSheet.hairlineWidth },
  label: { textAlign: 'center', fontSize: 13 },
  tick: { position: 'absolute', top: 2, fontSize: 10, transform: [{ translateX: -4 }] },
  part: { position: 'absolute', top: 2, bottom: 2, borderRadius: 8, borderWidth: 2, overflow: 'visible' },
  partImg: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, borderRadius: 6 },
  partNum: { position: 'absolute', left: 3, top: 3, width: 18, height: 18, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  partNumText: { color: '#fff', fontSize: 10, fontWeight: '800' },
  mute: { position: 'absolute', right: 3, bottom: 2, fontSize: 11 },
  block: { position: 'absolute', borderRadius: Radius.sm - 2, paddingHorizontal: 6, justifyContent: 'center', borderWidth: 2, overflow: 'visible' },
  selected: { zIndex: 4, shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 6, elevation: 6 },
  blockText: { fontSize: 11, fontWeight: '700' },
  handle: { position: 'absolute', top: -2, bottom: -2, width: 18, alignItems: 'center', justifyContent: 'center', zIndex: 6 },
  grip: { width: 6, height: '70%', minHeight: 14, borderRadius: 3, backgroundColor: '#fff', borderWidth: 1, borderColor: 'rgba(0,0,0,0.4)' },
  cue: { position: 'absolute', top: 1, width: 20, height: 20, borderRadius: 10, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  playhead: { position: 'absolute', top: 0, bottom: 0, width: 2, borderRadius: 1, zIndex: 10 },
});
