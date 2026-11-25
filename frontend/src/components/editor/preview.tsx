/**
 * Live preview of the edit, no export needed: plays the clips' upright copies part by part (trims,
 * order, mute, speed) and draws the captions, cards, effect labels and sound marks on top.
 * Colour looks and the exact effect animations only appear in an export.
 *
 * Time is owned by the editor: `time` comes in (seek when it moves while paused), and while playing
 * the player reports its position back through onTime.
 */

/* eslint-disable react-hooks/immutability -- expo-video's player is driven imperatively (seek, mute, replace) */
import { useEventListener } from 'expo';
import { VideoView, useVideoPlayer } from 'expo-video';
import { useEffect, useLayoutEffect, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Accent } from '@/constants/theme';
import type { SoundCue } from '@/lib/sfx-cues';
import type { Caption, Clip, EditPlan } from '@/lib/types';

const EFFECT_LABEL: Record<string, string> = {
  punch_in: '🔍 Punch in', slow_push: '🎥 Slow push', spotlight: '🔦 Spotlight', grade: '🎨 Colour look',
  freeze_frame: '⏸️ Freeze', flash: '⚡ Flash', countdown: '3️⃣ Countdown', backdrop_word: '🅰️ Word behind you',
  chat: '💬 Chat', counter: '🔢 Counter', graph: '📊 Graph', widgets: '🧊 Widgets', checklist: '✅ Checklist', progress: '📈 Progress',
  location: '📍 Location', name_card: '🪪 Name card', follow: '➕ Follow', emoji_burst: '🎉 Emojis', poll: '🗳️ Poll', timer: '⏱️ Timer',
  notification: '🔔 Notification', price_tag: '🏷️ Price tag',
};
const CAPTION_TOP = { upper_third: '16%', middle: '44%', lower_middle: '62%' } as const;

interface Span { start: number; end: number }

export function Preview({ plan, clips, shots, footage, total, time, playing, cues, onTime, onEnd }: {
  plan: EditPlan;
  clips: Record<string, Clip>;
  shots: Span[];
  footage: number;
  total: number;
  time: number;
  playing: boolean;
  cues: SoundCue[];
  onTime: (t: number) => void;
  onEnd: () => void;
}) {
  const player = useVideoPlayer(null, (p) => {
    p.loop = false;
    p.timeUpdateEventInterval = 0.05;
  });
  const loaded = useRef<string | null>(null);
  const part = useRef(0);
  const pendingSeek = useRef<number | null>(null);
  const reported = useRef(time);
  const settleUntil = useRef(0); // ignore stale time updates right after a jump
  const latest = useRef({ plan, clips, shots, footage, total, playing, onTime, onEnd });
  useLayoutEffect(() => {
    latest.current = { plan, clips, shots, footage, total, playing, onTime, onEnd };
  });

  const safePlay = () => {
    try {
      const r = player.play() as unknown;
      if (r instanceof Promise) r.catch(() => {}); // web: a load can interrupt play(); the next one carries on
    } catch {}
  };

  /** Load part i and put its clip at clipTime (seconds inside the clip). */
  const show = (i: number, clipTime: number) => {
    const { plan: p, clips: c } = latest.current;
    const shot = p.shots[i];
    if (!shot) return;
    const clip = c[shot.clip];
    const url = clip?.preview_url ?? clip?.download_url;
    part.current = i;
    player.muted = !shot.keep_audio;
    player.playbackRate = shot.speed || 1;
    settleUntil.current = Date.now() + 250;
    if (!url) return;
    if (loaded.current !== url) {
      loaded.current = url;
      pendingSeek.current = clipTime;
      player.replaceAsync({ uri: url }).catch(() => {}); // loads off the main thread (no UI freeze)
    } else {
      player.currentTime = clipTime;
    }
  };

  /** Reel time -> part and clip time. */
  const locate = (t: number) => {
    const { plan: p, shots: s } = latest.current;
    let i = s.findIndex((x) => t < x.end);
    if (i < 0) i = s.length - 1;
    const shot = p.shots[i];
    if (!shot) return null;
    const clipTime = Math.min(shot.out_s, shot.in_s + Math.max(0, t - s[i].start) * (shot.speed || 1));
    return { i, clipTime };
  };

  useEventListener(player, 'statusChange', ({ status }) => {
    if (status === 'readyToPlay' && pendingSeek.current !== null) {
      player.currentTime = pendingSeek.current;
      pendingSeek.current = null;
      if (latest.current.playing && reported.current < latest.current.footage) safePlay();
    }
  });

  useEventListener(player, 'timeUpdate', ({ currentTime }) => {
    const L = latest.current;
    if (!L.playing || Date.now() < settleUntil.current || pendingSeek.current !== null) return;
    const i = part.current;
    const shot = L.plan.shots[i];
    const span = L.shots[i];
    if (!shot || !span) return;
    if (currentTime >= shot.out_s - 0.04) {
      if (i + 1 < L.plan.shots.length) {
        show(i + 1, L.plan.shots[i + 1].in_s);
        reported.current = L.shots[i + 1].start;
      } else {
        player.pause(); // footage done: hold the last frame through the end card
        reported.current = L.footage;
      }
      L.onTime(reported.current);
      return;
    }
    const t = span.start + Math.max(0, currentTime - shot.in_s) / (shot.speed || 1);
    reported.current = Math.min(span.end, t);
    L.onTime(reported.current);
  });

  // the held tail after the footage (under the end card) has no video to clock it: count it here
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const L = latest.current;
      if (reported.current < L.footage - 0.01) return;
      reported.current = Math.min(L.total, reported.current + 0.05);
      L.onTime(reported.current);
      if (reported.current >= L.total - 0.001) L.onEnd();
    }, 50);
    return () => clearInterval(id);
  }, [playing]);

  // play / pause
  useEffect(() => {
    if (!playing) {
      player.pause();
      return;
    }
    const t = reported.current >= total - 0.05 ? 0 : reported.current;
    if (t !== reported.current) {
      reported.current = t;
      onTime(t);
    }
    const at = locate(Math.min(t, footage - 0.01));
    if (at && t < footage) {
      show(at.i, at.clipTime);
      if (pendingSeek.current === null) safePlay();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  // seek when the editor moves the playhead (scrubbing, tapping), not when it's our own report
  useEffect(() => {
    if (Math.abs(time - reported.current) < 0.12) return;
    reported.current = time;
    const at = locate(Math.min(time, footage - 0.01));
    if (at) show(at.i, at.clipTime);
    if (playing && time < footage && pendingSeek.current === null) safePlay();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [time]);

  // first frame, and again whenever the edit changes the part under the playhead
  const sig = JSON.stringify(plan.shots);
  useEffect(() => {
    const at = locate(Math.min(reported.current, footage - 0.01));
    if (at) show(at.i, at.clipTime);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  const caption = plan.captions.find((c) => time >= c.start_s && time < c.end_s);
  const effects = (plan.effects ?? []).filter((e) => time >= e.start_s && time < e.end_s);
  const card = plan.overlays.find((o) => time >= o.start_s && time < o.end_s);
  const cue = cues.find((c) => time >= c.at - 0.05 && time < c.at + 0.45);

  return (
    <View style={styles.frame}>
      <VideoView player={player} style={styles.video} contentFit="cover" nativeControls={false} />
      {effects.length ? (
        <View style={styles.fxRow} pointerEvents="none">
          {effects.map((e, k) => (
            <Text key={k} style={styles.fx}>{EFFECT_LABEL[e.type] ?? e.type}{e.text ? ` “${e.text}”` : ''}</Text>
          ))}
        </View>
      ) : null}
      {cue ? <Text style={styles.cue} pointerEvents="none">{cue.icon} {cue.name}</Text> : null}
      {caption ? <CaptionText c={caption} /> : null}
      {card ? (
        <View style={styles.card} pointerEvents="none">
          {card.title ? <Text style={styles.cardTitle}>{card.title}</Text> : null}
          {card.items.map((x) => (
            <Text key={x.label} style={styles.cardItem}><Text style={{ color: Accent }}>{x.value}</Text> {x.label}</Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function CaptionText({ c }: { c: Caption }) {
  const hi = c.highlight ? c.text.toLowerCase().indexOf(c.highlight.toLowerCase()) : -1;
  const parts = hi < 0 ? [c.text] : [c.text.slice(0, hi), c.text.slice(hi, hi + c.highlight!.length), c.text.slice(hi + c.highlight!.length)];
  return (
    <Text style={[styles.caption, { top: CAPTION_TOP[c.position] ?? '62%' }]} pointerEvents="none">
      {parts.map((p, k) => <Text key={k} style={k === 1 ? { color: Accent } : undefined}>{p}</Text>)}
    </Text>
  );
}

const shadow = { textShadowColor: 'rgba(0,0,0,0.85)', textShadowOffset: { width: 0, height: 1 }, textShadowRadius: 4 };

const styles = StyleSheet.create({
  frame: { height: '100%', aspectRatio: 9 / 16, backgroundColor: '#000', borderRadius: 14, overflow: 'hidden', alignSelf: 'center' },
  video: { position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' },
  caption: { position: 'absolute', left: '6%', right: '6%', textAlign: 'center', color: '#fff', fontSize: 17, fontWeight: '800', ...shadow },
  fxRow: { position: 'absolute', top: 8, left: 8, right: 8, flexDirection: 'row', flexWrap: 'wrap', gap: 4 },
  fx: { color: '#fff', fontSize: 11, fontWeight: '700', backgroundColor: 'rgba(255,90,31,0.85)', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, overflow: 'hidden' },
  cue: { position: 'absolute', right: 8, bottom: 8, color: '#fff', fontSize: 11, fontWeight: '700', backgroundColor: 'rgba(0,0,0,0.6)', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, overflow: 'hidden' },
  card: { position: 'absolute', left: '10%', right: '10%', top: '30%', backgroundColor: 'rgba(0,0,0,0.75)', borderRadius: 12, padding: 12, gap: 4, alignItems: 'center' },
  cardTitle: { color: '#fff', fontSize: 15, fontWeight: '800', textAlign: 'center' },
  cardItem: { color: '#fff', fontSize: 14, fontWeight: '700' },
});
