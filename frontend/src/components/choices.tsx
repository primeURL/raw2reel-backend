/**
 * "Captions & sounds": the creator picks how their reel looks and sounds, and sees it before any
 * editing happens. A live preview replays the caption animation and the transition on every tap.
 * Anything left on "Style" follows the reel's style.
 */

import { useQuery } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useEffect, useState } from 'react';
import { Animated, Easing, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { MusicPicker } from '@/components/music-picker';
import { Sheet } from '@/components/sheet';
import { Button } from '@/components/ui';
import { Accent, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { CaptionPrefs, Prefs } from '@/lib/types';

type Opt<T> = { value: T | null; label: string; hint?: string };

const ANIMATIONS: Opt<NonNullable<CaptionPrefs['animation']>>[] = [
  { value: null, label: 'Style' }, { value: 'pop', label: 'Pop' }, { value: 'typewriter', label: 'Typewriter' },
  { value: 'karaoke', label: 'Karaoke' }, { value: 'slide_up', label: 'Slide up' }, { value: 'fade', label: 'Fade' },
  { value: 'none', label: 'Still' },
];
const SIZES: Opt<NonNullable<CaptionPrefs['size']>>[] = [
  { value: null, label: 'Style' }, { value: 'small', label: 'Small' }, { value: 'medium', label: 'Medium' }, { value: 'large', label: 'Large' },
];
const POSITIONS: Opt<NonNullable<CaptionPrefs['position']>>[] = [
  { value: null, label: 'Auto' }, { value: 'upper_third', label: 'Top' }, { value: 'middle', label: 'Middle' }, { value: 'lower_middle', label: 'Bottom' },
];
const SOUNDS: Opt<NonNullable<Prefs['sound_effects']>>[] = [
  { value: null, label: 'Style', hint: 'As your style does' },
  { value: 'off', label: 'Off', hint: 'Just your voice' },
  { value: 'subtle', label: 'Subtle', hint: 'Whooshes and hits on effects' },
  { value: 'punchy', label: 'Punchy', hint: 'Also pops on key words' },
];
const TRANSITIONS: Opt<NonNullable<Prefs['transitions']>>[] = [
  { value: null, label: 'Style', hint: 'As your style does' },
  { value: 'cuts', label: 'Clean cuts', hint: 'Straight from clip to clip' },
  { value: 'smooth', label: 'Smooth', hint: 'A zoom on big scene changes' },
  { value: 'energetic', label: 'Energetic', hint: 'Whips, zooms and a flash' },
];
const EFFECTS: Opt<NonNullable<Prefs['effects']>>[] = [
  { value: null, label: 'Style', hint: 'As your style does' },
  { value: 'none', label: 'None', hint: 'Just the edit' },
  { value: 'few', label: 'A few', hint: 'On the strongest moments' },
  { value: 'lots', label: 'Lots', hint: 'Zooms, spotlight, word behind you…' },
];
const CASES: Opt<NonNullable<CaptionPrefs['case']>>[] = [
  { value: null, label: 'Style' }, { value: 'sentence', label: 'Normal' }, { value: 'upper', label: 'ALL CAPS' },
];
const VOLUMES: Opt<NonNullable<NonNullable<Prefs['music']>['volume']>>[] = [
  { value: null, label: 'Auto' }, { value: 'low_under_voice', label: 'Under my voice' }, { value: 'medium', label: 'Balanced' },
  { value: 'music_led', label: 'Music first' },
];
const SAMPLE = ['Chop', 'the', 'fresh', 'fruit'];
const SAMPLE_HI = 2; // "fresh" in the accent colour when highlights are on

export const EMPTY_PREFS: Prefs = { captions: {} };

/** One line for a summary row, e.g. "Typewriter captions · punchy sounds". */
export function prefsSummary(p: Prefs | null | undefined): string {
  if (!p) return 'Following your style';
  const parts: string[] = [];
  const c = p.captions ?? {};
  if (c.enabled === false) parts.push('No captions');
  else {
    if (c.look) parts.push(`${c.look.replace(/_/g, ' ')} look`);
    if (c.animation) parts.push(`${ANIMATIONS.find((a) => a.value === c.animation)?.label} captions`);
  }
  if (c.size) parts.push(`${c.size} text`);
  if (c.highlight === true) parts.push('key words highlighted');
  if (c.highlight === false) parts.push('no highlights');
  if (c.case === 'upper') parts.push('ALL CAPS');
  if (p.sound_effects) parts.push(`${p.sound_effects} sounds`);
  if (p.transitions) parts.push(`${TRANSITIONS.find((x) => x.value === p.transitions)?.label.toLowerCase()}`);
  if (p.effects) parts.push(`${p.effects === 'few' ? 'a few' : p.effects} effects`);
  if (p.music?.enabled === false) parts.push('no music');
  else if (p.music?.track) parts.push('your music');
  return parts.length ? parts.join(' · ') : 'Following your style';
}

export function ChoicesSheet({ open, value, onClose, onSave, background, saving, footerNote }: {
  open: boolean;
  value: Prefs | null | undefined;
  onClose: () => void;
  onSave: (p: Prefs) => void;
  background?: string | null; // a frame from the user's clip, when there is one
  saving?: boolean;
  footerNote?: string;
}) {
  const t = useTheme();
  const [p, setP] = useState<Prefs>(value ?? EMPTY_PREFS);
  const [seen, setSeen] = useState(open);
  if (open !== seen) {
    setSeen(open);
    if (open) setP(value ?? EMPTY_PREFS); // start from what's saved each time it opens
  }
  const cap = p.captions ?? {};
  const setCap = (patch: Partial<CaptionPrefs>) => setP((x) => ({ ...x, captions: { ...x.captions, ...patch } }));

  return (
    <Sheet open={open} onClose={onClose} title="Captions & sounds"
      footer={<Button label="Use these" style={{ flex: 1 }} loading={saving} onPress={() => onSave(p)} />}>
      <LivePreview prefs={p} background={background} />
      {footerNote ? <Text style={{ color: t.textSecondary, fontSize: 13 }}>{footerNote}</Text> : null}

      <Group title="Captions">
        <Chips options={[{ value: true, label: 'On' }, { value: false, label: 'Off' }]} value={cap.enabled === false ? false : true}
          onChange={(v) => setCap({ enabled: v ? null : false })} />
      </Group>
      {cap.enabled !== false ? (
        <>
          <Group title="Caption style"><LookGallery value={cap.look ?? null} onChange={(v) => setCap({ look: v })} /></Group>
          <Group title="How they appear"><Chips options={ANIMATIONS} value={cap.animation ?? null} onChange={(v) => setCap({ animation: v })} /></Group>
          <Group title="Size"><Chips options={SIZES} value={cap.size ?? null} onChange={(v) => setCap({ size: v })} /></Group>
          <Group title="Where"><Chips options={POSITIONS} value={cap.position ?? null} onChange={(v) => setCap({ position: v })} /></Group>
          <Group title="Highlight key words">
            <Chips options={[{ value: null, label: 'Style' }, { value: true, label: 'Yes' }, { value: false, label: 'No' }]}
              value={cap.highlight ?? null} onChange={(v) => setCap({ highlight: v })} />
          </Group>
          <Group title="Letters">
            <Chips options={CASES}
              value={cap.case ?? null} onChange={(v) => setCap({ case: v })} />
          </Group>
        </>
      ) : null}

      <Group title="Transitions between clips">
        <Cards options={TRANSITIONS} value={p.transitions ?? null} onChange={(v) => setP((x) => ({ ...x, transitions: v }))} />
      </Group>
      <Group title="Sound effects">
        <Cards options={SOUNDS} value={p.sound_effects ?? null} onChange={(v) => setP((x) => ({ ...x, sound_effects: v }))} />
      </Group>
      <Group title="Effects (zooms, spotlight, word behind you…)">
        <Cards options={EFFECTS} value={p.effects ?? null} onChange={(v) => setP((x) => ({ ...x, effects: v }))} />
      </Group>
      <Group title="Music">
        <MusicPicker active={open} value={p.music?.enabled === false ? false : p.music?.track ?? null}
          onChange={(v) => setP((x) => ({ ...x, music: { ...x.music, enabled: v === false ? false : null, track: v || null } }))} />
      </Group>
      {p.music?.enabled !== false ? (
        <Group title="Music volume">
          <Chips options={VOLUMES} value={p.music?.volume ?? null} onChange={(v) => setP((x) => ({ ...x, music: { ...x.music, volume: v } }))} />
        </Group>
      ) : null}
    </Sheet>
  );
}

/** Every caption look as the renderer draws it; tap one to use it. */
function LookGallery({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const t = useTheme();
  const q = useQuery({ queryKey: ['caption-looks'], queryFn: api.captionLooks, staleTime: 10 * 60_000 });
  if (!q.data) return <Text style={{ color: t.textSecondary, fontSize: 13 }}>{q.isError ? 'Couldn\u2019t load caption styles.' : 'Loading caption styles…'}</Text>;
  const chosen = q.data.looks.find((l) => l.id === value);
  return (
    <View style={{ gap: Spacing.one }}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: Spacing.two }}>
        <Pressable onPress={() => onChange(null)} style={[styles.lookTile, styles.lookStyle, { borderColor: value === null ? t.accent : t.border }]}>
          <Text style={{ color: value === null ? t.accent : t.text, fontWeight: '700' }}>Style</Text>
          <Text style={{ color: t.textSecondary, fontSize: 11, textAlign: 'center' }}>As your style does</Text>
        </Pressable>
        {q.data.looks.map((l) => {
          const on = l.id === value;
          return (
            <Pressable key={l.id} onPress={() => onChange(l.id)} style={{ gap: 2 }}>
              <View style={[styles.lookTile, { borderColor: on ? t.accent : t.border }]}>
                <Image source={{ uri: l.preview_url }} style={StyleSheet.absoluteFill} contentFit="cover" transition={120} />
              </View>
              <Text style={{ color: on ? t.accent : t.textSecondary, fontSize: 12, fontWeight: on ? '700' : '500' }}>{l.name}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {chosen?.animation ? (
        <Text style={{ color: t.textSecondary, fontSize: 12 }}>{chosen.name} always uses its own {chosen.animation} animation.</Text>
      ) : null}
    </View>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  const t = useTheme();
  return (
    <View style={{ gap: Spacing.two }}>
      <Text style={{ color: t.textSecondary, fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1 }}>{title}</Text>
      {children}
    </View>
  );
}

function Chips<T>({ options, value, onChange }: { options: Opt<T>[]; value: T | null; onChange: (v: T | null) => void }) {
  const t = useTheme();
  return (
    <View style={styles.chips}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable key={String(o.value)} onPress={() => onChange(o.value)}
            style={[styles.chip, { borderColor: on ? t.accent : t.border, backgroundColor: on ? t.accent + '22' : 'transparent' }]}>
            <Text style={{ color: on ? t.accent : t.text, fontWeight: '600' }}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Cards<T>({ options, value, onChange }: { options: Opt<T>[]; value: T | null; onChange: (v: T | null) => void }) {
  const t = useTheme();
  return (
    <View style={styles.cards}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable key={String(o.value)} onPress={() => onChange(o.value)}
            style={[styles.card, { borderColor: on ? t.accent : t.border, backgroundColor: on ? t.accent + '18' : t.background }]}>
            <Text style={{ color: on ? t.accent : t.text, fontWeight: '700' }}>{o.label}</Text>
            {o.hint ? <Text style={{ color: t.textSecondary, fontSize: 12 }}>{o.hint}</Text> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

// the live preview ------------------------------------------------------------------------

const TOP = { upper_third: '22%', middle: '44%', lower_middle: '62%' } as const;
const FONT = { small: 15, medium: 18, large: 22 } as const;

/** A phone frame replaying the caption animation (and the transition) with the current choices. */
function LivePreview({ prefs, background }: { prefs: Prefs; background?: string | null }) {
  const cap = prefs.captions ?? {};
  const anim = cap.animation ?? 'pop';
  const key = JSON.stringify(prefs);
  const [enter] = useState(() => new Animated.Value(0));
  const [swap] = useState(() => new Animated.Value(0));
  const [words, setWords] = useState(SAMPLE.length);
  const [scene, setScene] = useState(0);

  // caption: in, hold, out - again and again; restarts on every change
  useEffect(() => {
    let alive = true;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const run = () => {
      if (!alive) return;
      enter.setValue(0);
      if (anim === 'typewriter') {
        enter.setValue(1);
        SAMPLE.forEach((_, k) => timers.push(setTimeout(() => alive && setWords(k + 1), 140 * k)));
      } else {
        setWords(SAMPLE.length);
        Animated.timing(enter, { toValue: 1, duration: anim === 'none' ? 0 : anim === 'fade' ? 300 : 220, easing: Easing.out(Easing.back(anim === 'pop' ? 2.2 : 0)), useNativeDriver: true }).start();
      }
      timers.push(setTimeout(run, 2200));
    };
    run();
    return () => {
      alive = false;
      timers.forEach(clearTimeout);
    };
  }, [anim, enter]);

  // transition: switch between two scenes every 2.2 s the chosen way
  useEffect(() => {
    const id = setInterval(() => {
      swap.setValue(0);
      Animated.timing(swap, { toValue: 1, duration: 320, useNativeDriver: true }).start();
      setTimeout(() => setScene((s) => 1 - s), 160);
    }, 2200);
    return () => clearInterval(id);
  }, [swap, key]);

  const tr = prefs.transitions;
  const peak = swap.interpolate({ inputRange: [0, 0.5, 1], outputRange: [0, 1, 0] });
  const sceneStyle = tr === 'energetic'
    ? { transform: [{ translateX: swap.interpolate({ inputRange: [0, 0.49, 0.5, 1], outputRange: [0, -60, 60, 0] }) }] }
    : tr === 'smooth' ? { transform: [{ scale: peak.interpolate({ inputRange: [0, 1], outputRange: [1, 1.18] }) }] } : null;
  const capStyle = anim === 'pop'
    ? { opacity: enter.interpolate({ inputRange: [0, 0.3, 1], outputRange: [0, 1, 1] }), transform: [{ scale: enter.interpolate({ inputRange: [0, 1], outputRange: [0.75, 1] }) }] }
    : anim === 'slide_up'
      ? { opacity: enter, transform: [{ translateY: enter.interpolate({ inputRange: [0, 1], outputRange: [22, 0] }) }] }
      : anim === 'fade' ? { opacity: enter } : null;

  const caps = cap.case === 'upper';
  const highlight = cap.highlight !== false;
  return (
    <View style={styles.preview}>
      <Animated.View style={[StyleSheet.absoluteFill, sceneStyle]}>
        {background && scene === 0 ? <Image source={{ uri: background }} style={StyleSheet.absoluteFill} contentFit="cover" /> : (
          <View style={[StyleSheet.absoluteFill, { backgroundColor: scene === 0 ? '#5B3A29' : '#24505A' }]}>
            <Text style={styles.sceneEmoji}>{scene === 0 ? '🍎' : '🥣'}</Text>
          </View>
        )}
      </Animated.View>
      {tr === 'energetic' ? <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, { backgroundColor: '#fff', opacity: peak.interpolate({ inputRange: [0, 1], outputRange: [0, 0.55] }) }]} /> : null}
      {cap.enabled !== false ? (
        <Animated.Text style={[styles.cap, { top: TOP[cap.position ?? 'lower_middle'], fontSize: FONT[cap.size ?? 'medium'] }, capStyle]}>
          {SAMPLE.slice(0, words).map((w, k) => (
            <Text key={k} style={k === SAMPLE_HI && highlight ? { color: Accent } : undefined}>{(caps ? w.toUpperCase() : w) + (k < words - 1 ? ' ' : '')}</Text>
          ))}
        </Animated.Text>
      ) : null}
      <Text style={styles.tag}>{prefs.sound_effects === 'off' ? '🔈 no sound effects' : prefs.sound_effects === 'punchy' ? '🔊 punchy' : '🔉 sounds'}</Text>
    </View>
  );
}

const shadow = { textShadowColor: 'rgba(0,0,0,0.9)', textShadowOffset: { width: 0, height: 1 }, textShadowRadius: 4 };

const styles = StyleSheet.create({
  lookTile: { width: 160, height: 90, borderRadius: Radius.md, borderWidth: 2, overflow: 'hidden' },
  lookStyle: { alignItems: 'center', justifyContent: 'center', gap: 2, padding: Spacing.one },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  chip: { borderWidth: 1, borderRadius: Radius.pill, paddingHorizontal: Spacing.three, paddingVertical: 7 },
  cards: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  card: { flexGrow: 1, flexBasis: '45%', borderWidth: 1.5, borderRadius: Radius.md, padding: Spacing.two, gap: 2 },
  preview: { width: 170, aspectRatio: 9 / 16, alignSelf: 'center', borderRadius: Radius.lg, overflow: 'hidden', backgroundColor: '#000' },
  sceneEmoji: { position: 'absolute', top: '30%', width: '100%', textAlign: 'center', fontSize: 48, opacity: 0.85 },
  cap: { position: 'absolute', left: 8, right: 8, textAlign: 'center', color: '#fff', fontWeight: '800', ...shadow },
  tag: { position: 'absolute', right: 6, bottom: 6, color: '#fff', fontSize: 10, fontWeight: '700', backgroundColor: 'rgba(0,0,0,0.55)', paddingHorizontal: 5, paddingVertical: 2, borderRadius: 5, overflow: 'hidden' },
});
