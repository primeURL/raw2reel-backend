import { Stack } from 'expo-router';

import { useTheme } from '@/hooks/use-theme';

export default function ReelsLayout() {
  const t = useTheme();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: t.background },
        headerTintColor: t.accent,
        headerTitleStyle: { color: t.text },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: t.background },
      }}>
      <Stack.Screen name="index" options={{ headerShown: false }} />
      <Stack.Screen name="reel/new" options={{ title: 'New reel', presentation: 'modal' }} />
      <Stack.Screen name="reel/[id]" options={{ title: 'Reel' }} />
      <Stack.Screen name="reel/plan/[id]" options={{ title: 'Edit plan' }} />
      <Stack.Screen name="reel/watch/[renderId]" options={{ title: 'Watch' }} />
    </Stack>
  );
}
