/** "This uses 1 AI edit (N of M left today)" - shown before every AI call so credit is never spent by accident. */

import { useQuery } from '@tanstack/react-query';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card } from '@/components/ui';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';

export function ConfirmAI({ title, note, confirmLabel, onConfirm, onCancel, loading, error }: {
  title: string;
  note?: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  error?: string | null;
}) {
  const t = useTheme();
  const usage = useQuery({ queryKey: ['ai-usage'], queryFn: api.aiUsage });
  const left = usage.data ? usage.data.daily_limit - usage.data.calls_last_24h : null;
  return (
    <Card style={{ borderColor: t.accent }}>
      <Text style={[styles.title, { color: t.text }]}>{title}</Text>
      <Text style={{ color: t.textSecondary }}>
        This uses 1 AI edit{left !== null ? ` (${left} of ${usage.data!.daily_limit} left today)` : ''}.{note ? ` ${note}` : ''}
      </Text>
      {left === 0 ? <Text style={{ color: t.danger }}>You&apos;ve used today&apos;s AI edits. Try again tomorrow.</Text> : null}
      {error ? <Text style={{ color: t.danger }}>{error}</Text> : null}
      <View style={styles.row}>
        <Button label="Cancel" kind="secondary" onPress={onCancel} style={{ flex: 1 }} />
        <Button label={confirmLabel} onPress={onConfirm} loading={loading} disabled={left === 0} style={{ flex: 1 }} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 16, fontWeight: '600' },
  row: { flexDirection: 'row', gap: Spacing.two },
});
