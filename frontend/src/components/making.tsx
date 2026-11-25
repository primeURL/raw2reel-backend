/** "Making your reel": what the AI is doing right now, as a checklist that ticks along. */

import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { Card } from '@/components/ui';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/** Steps of one plan call, with the second each usually starts at. The call does them all at once,
 * so the ticks follow typical timings; the last stays open until the plan really arrives. */
const PLAN_STEPS: [string, number][] = [
  ['Listening to your clips', 0],
  ['Picking your best takes', 5],
  ['Cutting pauses and retakes', 10],
  ['Writing captions in your style', 16],
  ['Adding zooms, effects and sounds', 24],
];

export function Making({ since, title = 'Making your reel', thumbs }: { since: string; title?: string; thumbs?: React.ReactNode }) {
  const t = useTheme();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const elapsed = Math.max(0, (now - new Date(since).getTime()) / 1000);
  const current = PLAN_STEPS.reduce((k, [, at], i) => (elapsed >= at ? i : k), 0);

  return (
    <Card style={{ borderColor: t.accent, gap: Spacing.three }}>
      <Text style={[styles.title, { color: t.text }]}>{title}</Text>
      {thumbs}
      <View style={{ gap: Spacing.two }}>
        {PLAN_STEPS.map(([label], i) => (
          <View key={label} style={styles.row}>
            <View style={styles.icon}>
              {i < current ? <Text style={{ color: t.success, fontWeight: '800' }}>✓</Text>
                : i === current ? <ActivityIndicator size="small" color={t.accent} style={{ transform: [{ scale: 0.75 }] }} />
                  : <View style={[styles.dot, { borderColor: t.border }]} />}
            </View>
            <Text style={{ color: i <= current ? t.text : t.textSecondary, fontSize: 15, fontWeight: i === current ? '600' : '400' }}>{label}</Text>
          </View>
        ))}
      </View>
      <Text style={{ color: t.textSecondary, fontSize: 13 }}>Usually about half a minute. You can leave this screen.</Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 18, fontWeight: '700' },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  icon: { width: 22, alignItems: 'center' },
  dot: { width: 12, height: 12, borderRadius: 6, borderWidth: 2 },
});
