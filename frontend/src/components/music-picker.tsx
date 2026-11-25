/**
 * Pick the background music: "Let AI pick", "No music", or a track from the library, each with a
 * 20-second preview (▶). Only previews are streamed; full tracks stay on the server.
 */

import { useQuery } from '@tanstack/react-query';
import { setAudioModeAsync, useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import type { MusicTrack } from '@/lib/types';

const ENERGY = { calm: 'calm', medium: 'steady', high: 'high energy' } as const;
const AUTO = '__auto__';
const NONE = '__none__';

/** value: undefined/null = AI picks, false = no music, a track id = that track. */
export function MusicPicker({ active, value, onChange }: {
  active: boolean; // stop the preview when the sheet closes
  value: string | false | null | undefined;
  onChange: (v: string | false | null) => void;
}) {
  const t = useTheme();
  const lib = useQuery({ queryKey: ['music'], queryFn: api.music, staleTime: 5 * 60_000 });
  const [mood, setMood] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const player = useAudioPlayer(null);
  const status = useAudioPlayerStatus(player);

  useEffect(() => {
    if (!active) {
      player.pause();
      setPlaying(null); // eslint-disable-line react-hooks/set-state-in-effect -- the sheet closing stops the preview
    }
  }, [active, player]);
  useEffect(() => {
    if (status.didJustFinish) setPlaying(null); // eslint-disable-line react-hooks/set-state-in-effect -- player event
  }, [status.didJustFinish]);

  async function toggle(tr: MusicTrack) {
    if (playing === tr.id) {
      player.pause();
      setPlaying(null);
      return;
    }
    if (!tr.preview_url) return;
    try {
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false });
    } catch {}
    player.replace({ uri: tr.preview_url });
    player.play();
    setPlaying(tr.id);
  }

  const tracks = (lib.data?.tracks ?? []).filter((x) => !mood || x.moods.includes(mood));
  const sel = value === false ? NONE : value || AUTO;

  return (
    <View style={{ gap: Spacing.two }}>
      <View style={styles.row}>
        <Pill label="✨ Let AI pick" on={sel === AUTO} onPress={() => onChange(null)} />
        <Pill label="🔇 No music" on={sel === NONE} onPress={() => onChange(false)} />
      </View>
      {lib.isLoading ? <ActivityIndicator /> : null}
      {lib.isError ? <Text style={{ color: t.danger }}>Couldn&apos;t load the music list.</Text> : null}
      {lib.data && !lib.data.tracks.length ? (
        <Text style={{ color: t.textSecondary, fontSize: 13 }}>The music library is being filled. Your reel gets music as soon as it has tracks.</Text>
      ) : null}
      {lib.data?.moods.length ? (
        <View style={styles.row}>
          <Pill small label="All" on={!mood} onPress={() => setMood(null)} />
          {lib.data.moods.map((m) => <Pill small key={m.id} label={m.id} on={mood === m.id} onPress={() => setMood(mood === m.id ? null : m.id)} />)}
        </View>
      ) : null}
      {tracks.map((tr) => {
        const on = sel === tr.id;
        return (
          <Pressable key={tr.id} onPress={() => onChange(tr.id)}
            style={[styles.track, { borderColor: on ? t.accent : t.border, backgroundColor: on ? t.accent + '14' : t.background }]}>
            <Pressable hitSlop={8} onPress={() => toggle(tr)} accessibilityLabel={playing === tr.id ? 'Stop preview' : 'Play preview'}
              style={[styles.play, { backgroundColor: playing === tr.id ? t.accent : t.backgroundElement }]}>
              <Text style={{ color: playing === tr.id ? t.onAccent : t.text, fontSize: 14 }}>{playing === tr.id ? '❚❚' : '▶'}</Text>
            </Pressable>
            <View style={{ flex: 1 }}>
              <Text style={{ color: on ? t.accent : t.text, fontWeight: '700' }} numberOfLines={1}>{tr.title}</Text>
              <Text style={{ color: t.textSecondary, fontSize: 12 }} numberOfLines={1}>
                {[tr.moods.join(', '), tr.energy ? ENERGY[tr.energy] : null, tr.duration_s ? `${Math.floor(tr.duration_s / 60)}:${String(Math.round(tr.duration_s % 60)).padStart(2, '0')}` : null].filter(Boolean).join(' · ')}
              </Text>
            </View>
            {on ? <Text style={{ color: t.accent, fontWeight: '800' }}>✓</Text> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

function Pill({ label, on, onPress, small }: { label: string; on: boolean; onPress: () => void; small?: boolean }) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} style={[styles.pill, small && styles.pillSmall, { borderColor: on ? t.accent : t.border, backgroundColor: on ? t.accent + '18' : t.background }]}>
      <Text style={{ color: on ? t.accent : t.text, fontWeight: '600', fontSize: small ? 13 : 14 }}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  pill: { borderWidth: 1, borderRadius: Radius.md, paddingHorizontal: Spacing.three, paddingVertical: Spacing.two },
  pillSmall: { paddingHorizontal: Spacing.two, paddingVertical: 4 },
  track: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, borderWidth: 1, borderRadius: Radius.md, padding: Spacing.two },
  play: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
});
