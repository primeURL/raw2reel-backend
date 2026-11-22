/** Name a new style, then go add its reference reels. */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Stack, router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Field } from '@/components/ui';
import { MaxContentWidth, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';

export default function NewStyleScreen() {
  const t = useTheme();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const create = useMutation({
    mutationFn: () => api.createStyle(name.trim() || 'My style'),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ['styles'] });
      router.replace({ pathname: '/styles/[id]', params: { id: s.id } });
    },
  });

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: t.background }]} edges={['bottom']}>
      <Stack.Screen
        options={{
          headerLeft: () => (
            <Button label="Cancel" kind="ghost" style={{ minHeight: 36, paddingHorizontal: Spacing.three }}
              onPress={() => (router.canGoBack() ? router.back() : router.replace('/styles'))} />
          ),
        }}
      />
      <View style={styles.wrap}>
        <Text style={[styles.lead, { color: t.text }]}>What should we call this style?</Text>
        <Text style={[styles.body, { color: t.textSecondary }]}>
          Next you&apos;ll add 3-4 reels whose editing you love. Raw2Reel takes the pacing, captions and feel - never their exact
          music, fonts or logos.
        </Text>
        <Field
          label="Style name"
          value={name}
          onChangeText={setName}
          placeholder="e.g. Road Log"
          maxLength={120}
          autoFocus
          returnKeyType="done"
          onSubmitEditing={() => create.mutate()}
        />
        {create.isError ? <Text style={{ color: t.danger }}>{create.error.message}</Text> : null}
        <Button label="Continue" onPress={() => create.mutate()} loading={create.isPending} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  wrap: { padding: Spacing.four, gap: Spacing.three, width: '100%', maxWidth: MaxContentWidth, alignSelf: 'center' },
  lead: { fontSize: 22, fontWeight: '700' },
  body: { fontSize: 15, lineHeight: 21 },
});
