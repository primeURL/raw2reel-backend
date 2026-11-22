/** 🎤 Tap to talk, tap again to stop: the note is transcribed on the server (free Whisper, no AI
 * credit) and the text handed to onText. Max 3 minutes. */

import { RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioRecorder, useAudioRecorderState } from 'expo-audio';
import { useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { transcribe } from '@/lib/voice';

const MAX_MS = 180_000;

export function VoiceButton({ onText, language, label = 'Speak instead' }: {
  onText: (text: string) => void;
  language?: string | null;
  label?: string;
}) {
  const t = useTheme();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const state = useAudioRecorderState(recorder, 250);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const limit = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function start() {
    setError(null);
    const perm = await requestRecordingPermissionsAsync();
    if (!perm.granted) {
      setError('Allow the microphone to speak your script.');
      return;
    }
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
    limit.current = setTimeout(() => void stop(), MAX_MS); // stop by itself at the limit
  }

  async function stop() {
    if (limit.current) clearTimeout(limit.current);
    limit.current = null;
    await recorder.stop();
    await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
    const uri = recorder.uri;
    if (!uri) return;
    setBusy(true);
    try {
      const text = await transcribe(uri, language);
      if (text) onText(text);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Voice note failed');
    } finally {
      setBusy(false);
    }
  }

  const recording = state.isRecording;
  const secs = Math.floor((state.durationMillis ?? 0) / 1000);
  return (
    <View style={{ gap: Spacing.one }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={recording ? 'Stop recording' : 'Record your script'}
        disabled={busy}
        onPress={recording ? stop : start}
        style={({ pressed }) => [
          styles.button,
          { borderColor: recording ? t.danger : t.border, backgroundColor: recording ? t.danger + '22' : t.backgroundElement, opacity: pressed || busy ? 0.7 : 1 },
        ]}>
        {busy ? <ActivityIndicator color={t.accent} /> : <View style={[styles.dot, { backgroundColor: recording ? t.danger : t.accent }]} />}
        <Text style={[styles.text, { color: recording ? t.danger : t.text }]}>
          {busy ? 'Typing what you said…' : recording ? `Recording ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')} - tap to stop` : `🎤 ${label}`}
        </Text>
      </Pressable>
      {error ? <Text style={{ color: t.danger, fontSize: 13 }}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  button: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, borderWidth: 1, borderRadius: Radius.md, paddingHorizontal: Spacing.three, minHeight: 44 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  text: { fontSize: 15, fontWeight: '600' },
});
