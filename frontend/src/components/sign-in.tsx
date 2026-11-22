/** Shown when nobody is signed in. Google sign-in arrives with Firebase; until then a dev sign-in
 * (backend AUTH_DEV_BYPASS) lets us use the real API. */

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { API_URL, DEV_LOGIN } from '@/lib/config';
import { useSession } from '@/lib/session';

export function SignIn() {
  const t = useTheme();
  const { signInDev } = useSession();
  const [userId, setUserId] = useState('utkarsh');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    if (!userId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await signInDev(userId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: t.background }]}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.wrap}>
        <View style={styles.brand}>
          <Text style={[styles.logo, { color: t.text }]}>
            Raw<Text style={{ color: t.accent }}>2</Text>Reel
          </Text>
          <Text style={[styles.tagline, { color: t.textSecondary }]}>Raw clips in. Your reel out.</Text>
        </View>

        <View style={styles.actions}>
          <Button label="Continue with Google (coming soon)" disabled kind="secondary" />

          {DEV_LOGIN ? (
            <View style={[styles.dev, { borderColor: t.border }]}>
              <Text style={[styles.devLabel, { color: t.textSecondary }]}>Developer sign-in</Text>
              <TextInput
                value={userId}
                onChangeText={setUserId}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="user id"
                placeholderTextColor={t.textSecondary}
                onSubmitEditing={go}
                style={[styles.input, { color: t.text, backgroundColor: t.backgroundElement, borderColor: t.border }]}
              />
              <Button label="Sign in" onPress={go} loading={busy} />
              {error ? <Text style={[styles.error, { color: t.danger }]}>{error}</Text> : null}
              <Text style={[styles.hint, { color: t.textSecondary }]}>Server: {API_URL}</Text>
            </View>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  wrap: { flex: 1, justifyContent: 'space-between', padding: Spacing.four, maxWidth: 480, width: '100%', alignSelf: 'center' },
  brand: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: Spacing.two },
  logo: { fontSize: 44, fontWeight: '800', letterSpacing: -1 },
  tagline: { fontSize: 17 },
  actions: { gap: Spacing.three, paddingBottom: Spacing.four },
  dev: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: Spacing.three, gap: Spacing.two },
  devLabel: { fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1 },
  input: { height: 48, borderRadius: Radius.md, borderWidth: 1, paddingHorizontal: Spacing.three, fontSize: 16 },
  error: { fontSize: 14 },
  hint: { fontSize: 12 },
});
