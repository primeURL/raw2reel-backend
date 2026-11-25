import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { useColorScheme } from 'react-native';

import AppTabs from '@/components/app-tabs';
import { Onboarding, useOnboarding } from '@/components/onboarding';
import { SignIn } from '@/components/sign-in';
import { Colors } from '@/constants/theme';
import { SessionProvider, useSession } from '@/lib/session';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const scheme = useColorScheme();
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 10_000 } } }),
  );
  const colors = Colors[scheme === 'dark' ? 'dark' : 'light'];
  const base = scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navTheme = { ...base, colors: { ...base.colors, primary: colors.accent, background: colors.background, card: colors.background } };

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <ThemeProvider value={navTheme}>
          <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
          <Gate />
        </ThemeProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}

/** Splash until the saved session is checked, then sign-in or the app. */
function Gate() {
  const { ready, me } = useSession();
  const intro = useOnboarding();
  useEffect(() => {
    if (ready && intro.show !== null) SplashScreen.hideAsync();
  }, [ready, intro.show]);
  if (!ready || intro.show === null) return null;
  if (!me) return <SignIn />;
  return intro.show ? <Onboarding name={me.name} onDone={intro.done} /> : <AppTabs />;
}
