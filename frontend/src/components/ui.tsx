/** Small shared building blocks: screen frame, buttons, cards, status chips, empty/error states. */

import { type ReactNode, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, type TextInputProps, View, type ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BottomTabInset, MaxContentWidth, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/** onRefresh: pull-to-refresh. The spinner shows only while the user's own pull is running -
 * not during the background polling that keeps statuses fresh (that made it flash every 3 s). */
export function Screen({ title, subtitle, right, children, onRefresh, sticky }: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  onRefresh?: () => unknown;
  /** stays pinned to the top while the rest scrolls (e.g. tabs) */
  sticky?: ReactNode;
}) {
  const t = useTheme();
  const [pulling, setPulling] = useState(false);
  const pull = async () => {
    setPulling(true);
    try {
      await onRefresh?.();
    } finally {
      setPulling(false);
    }
  };
  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: t.background }]} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        stickyHeaderIndices={sticky ? [1] : undefined}
        refreshControl={onRefresh ? <RefreshControl refreshing={pulling} onRefresh={pull} tintColor={t.accent} colors={[t.accent]} progressBackgroundColor={t.backgroundElement} /> : undefined}>
        <View style={styles.inner}>
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={[styles.title, { color: t.text }]}>{title}</Text>
              {subtitle ? <Text style={[styles.subtitle, { color: t.textSecondary }]}>{subtitle}</Text> : null}
            </View>
            {right}
          </View>
        </View>
        {sticky ? <View style={[styles.stickyWrap, { backgroundColor: t.background }]}><View style={styles.inner}>{sticky}</View></View> : null}
        <View style={[styles.inner, { paddingTop: Spacing.three }]}>{children}</View>
      </ScrollView>
    </SafeAreaView>
  );
}

export function Button({ label, onPress, kind = 'primary', loading, disabled, style }: {
  label: string;
  onPress?: () => void;
  kind?: 'primary' | 'secondary' | 'ghost';
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}) {
  const t = useTheme();
  const bg = kind === 'primary' ? t.accent : kind === 'secondary' ? t.backgroundSelected : 'transparent';
  const fg = kind === 'primary' ? t.onAccent : kind === 'ghost' ? t.accent : t.text;
  const off = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={off ? undefined : onPress}
      style={({ pressed }) => [styles.button, { backgroundColor: bg, opacity: off ? 0.5 : pressed ? 0.8 : 1 }, style]}>
      {loading ? <ActivityIndicator color={fg} /> : <Text style={[styles.buttonText, { color: fg }]}>{label}</Text>}
    </Pressable>
  );
}

export function Card({ children, onPress, style }: { children: ReactNode; onPress?: () => void; style?: ViewStyle }) {
  const t = useTheme();
  const base = [styles.card, { backgroundColor: t.backgroundElement, borderColor: t.border }, style];
  if (!onPress) return <View style={base}>{children}</View>;
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [...base, pressed && { opacity: 0.85 }]}>
      {children}
    </Pressable>
  );
}

const STATUS: Record<string, { label: string; tone: 'muted' | 'busy' | 'good' | 'warn' | 'bad' }> = {
  draft: { label: 'Draft', tone: 'muted' },
  analyzing: { label: 'Working…', tone: 'busy' },
  planned: { label: 'Plan ready', tone: 'warn' },
  rendering: { label: 'Rendering…', tone: 'busy' },
  done: { label: 'Done', tone: 'good' },
  failed: { label: 'Failed', tone: 'bad' },
  needs_answers: { label: '3 questions', tone: 'warn' },
  ready: { label: 'Ready', tone: 'good' },
};

export function StatusChip({ status }: { status: string }) {
  const t = useTheme();
  const s = STATUS[status] ?? { label: status, tone: 'muted' as const };
  const color = { muted: t.textSecondary, busy: t.accent, good: t.success, warn: t.accent, bad: t.danger }[s.tone];
  return (
    <View style={[styles.chip, { borderColor: color }]}>
      {s.tone === 'busy' ? <ActivityIndicator size="small" color={color} style={{ transform: [{ scale: 0.6 }] }} /> : null}
      <Text style={[styles.chipText, { color }]}>{s.label}</Text>
    </View>
  );
}

export function Message({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  const t = useTheme();
  return (
    <View style={styles.message}>
      <Text style={[styles.messageTitle, { color: t.text }]}>{title}</Text>
      {body ? <Text style={[styles.messageBody, { color: t.textSecondary }]}>{body}</Text> : null}
      {action}
    </View>
  );
}

export function Field(props: TextInputProps & { label?: string }) {
  const t = useTheme();
  const { label, style, ...rest } = props;
  return (
    <View style={{ gap: Spacing.one }}>
      {label ? <Text style={[styles.label, { color: t.textSecondary }]}>{label}</Text> : null}
      <TextInput
        placeholderTextColor={t.textSecondary}
        {...rest}
        style={[styles.field, { color: t.text, backgroundColor: t.backgroundElement, borderColor: t.border }, rest.multiline && styles.fieldMulti, style]}
      />
    </View>
  );
}

/** Tappable answer option. */
export function Choice({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={[styles.choice, { borderColor: selected ? t.accent : t.border, backgroundColor: selected ? t.accent + '22' : 'transparent' }]}>
      <Text style={[styles.choiceText, { color: selected ? t.accent : t.text }]}>{label}</Text>
    </Pressable>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  const t = useTheme();
  return <Text style={[styles.label, { color: t.textSecondary, marginTop: Spacing.two }]}>{children}</Text>;
}

/** Thin progress bar with an optional label, e.g. "42% · Adding captions". */
export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const t = useTheme();
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <View style={{ gap: Spacing.one }}>
      {label ? <Text style={{ color: t.accent, fontSize: 13, fontWeight: '600' }}>{pct}% · {label}</Text> : null}
      <View style={[styles.track, { backgroundColor: t.backgroundSelected }]}>
        <View style={[styles.trackFill, { width: `${pct}%`, backgroundColor: t.accent }]} />
      </View>
    </View>
  );
}

export function Loading() {
  const t = useTheme();
  return <ActivityIndicator style={{ marginTop: Spacing.five }} color={t.accent} />;
}

export function formatSeconds(s: number): string {
  if (!s) return '0s';
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return m ? `${m}:${String(r).padStart(2, '0')}` : `${r}s`;
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  scroll: { paddingBottom: BottomTabInset + Spacing.six },
  stickyWrap: { width: '100%', alignItems: 'center', paddingVertical: Spacing.two },
  inner: { width: '100%', maxWidth: MaxContentWidth, alignSelf: 'center', paddingHorizontal: Spacing.three, gap: Spacing.three },
  header: { flexDirection: 'row', alignItems: 'center', paddingTop: Spacing.four, gap: Spacing.three },
  title: { fontSize: 32, fontWeight: '700', letterSpacing: -0.5 },
  subtitle: { fontSize: 15, marginTop: Spacing.one },
  button: { minHeight: 48, borderRadius: Radius.md, paddingHorizontal: Spacing.four, alignItems: 'center', justifyContent: 'center' },
  buttonText: { fontSize: 16, fontWeight: '600' },
  card: { borderRadius: Radius.lg, borderWidth: StyleSheet.hairlineWidth, padding: Spacing.three, gap: Spacing.two },
  chip: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', borderWidth: 1, borderRadius: Radius.pill, paddingHorizontal: Spacing.two, height: 24 },
  chipText: { fontSize: 12, fontWeight: '600' },
  message: { alignItems: 'center', paddingVertical: Spacing.six, gap: Spacing.two },
  messageTitle: { fontSize: 18, fontWeight: '600', textAlign: 'center' },
  messageBody: { fontSize: 15, textAlign: 'center', maxWidth: 360, marginBottom: Spacing.two },
  label: { fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1 },
  field: { minHeight: 48, borderRadius: Radius.md, borderWidth: 1, paddingHorizontal: Spacing.three, fontSize: 16 },
  fieldMulti: { minHeight: 96, paddingTop: Spacing.three, textAlignVertical: 'top' },
  choice: { borderWidth: 1, borderRadius: Radius.pill, paddingHorizontal: Spacing.three, paddingVertical: Spacing.two },
  choiceText: { fontSize: 15, fontWeight: '500' },
  track: { height: 6, borderRadius: Radius.pill, overflow: 'hidden' },
  trackFill: { height: '100%', borderRadius: Radius.pill },
});
