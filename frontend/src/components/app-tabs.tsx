import { NativeTabs } from 'expo-router/native-tabs';
import { useColorScheme } from 'react-native';

import { Colors } from '@/constants/theme';

export default function AppTabs() {
  const scheme = useColorScheme();
  const colors = Colors[scheme === 'dark' ? 'dark' : 'light'];

  return (
    <NativeTabs
      backgroundColor={colors.background}
      indicatorColor={colors.backgroundSelected}
      labelStyle={{ selected: { color: colors.accent } }}
      tintColor={colors.accent}>
      <NativeTabs.Trigger name="(reels)">
        <NativeTabs.Trigger.Label>Reels</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf={{ default: 'film', selected: 'film.fill' }} md="movie" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="styles">
        <NativeTabs.Trigger.Label>Styles</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf={{ default: 'paintpalette', selected: 'paintpalette.fill' }} md="palette" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="profile">
        <NativeTabs.Trigger.Label>Profile</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf={{ default: 'person.crop.circle', selected: 'person.crop.circle.fill' }} md="account_circle" />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
