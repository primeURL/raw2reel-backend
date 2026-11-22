import { Stack } from 'expo-router';

import { useTheme } from '@/hooks/use-theme';

export default function StylesLayout() {
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
      <Stack.Screen name="new" options={{ title: 'New style', presentation: 'modal' }} />
      <Stack.Screen name="[id]" options={{ title: 'Style' }} />
    </Stack>
  );
}
