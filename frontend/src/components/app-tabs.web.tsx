import { Tabs, TabList, TabTrigger, TabSlot, TabTriggerSlotProps, TabListProps } from 'expo-router/ui';
import { Pressable, type PressableProps, StyleSheet, Text, View } from 'react-native';

import { MaxContentWidth, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

export default function AppTabs() {
  return (
    <Tabs>
      <TabSlot style={{ height: '100%' }} />
      <TabList asChild>
        <BottomBar>
          <TabTrigger name="(reels)" href="/" asChild>
            <TabButton>Reels</TabButton>
          </TabTrigger>
          <TabTrigger name="styles" href="/styles" asChild>
            <TabButton>Styles</TabButton>
          </TabTrigger>
          <TabTrigger name="profile" href="/profile" asChild>
            <TabButton>Profile</TabButton>
          </TabTrigger>
        </BottomBar>
      </TabList>
    </Tabs>
  );
}

function TabButton({ children, isFocused, ref: _ref, ...props }: TabTriggerSlotProps) {
  const t = useTheme();
  return (
    <Pressable {...(props as PressableProps)} style={({ pressed }) => [styles.tab, pressed && { opacity: 0.7 }]}>
      <Text style={[styles.tabText, { color: isFocused ? t.accent : t.textSecondary }]}>{children}</Text>
    </Pressable>
  );
}

function BottomBar(props: TabListProps) {
  const t = useTheme();
  return (
    <View {...props} style={[styles.bar, { backgroundColor: t.backgroundElement, borderColor: t.border }]}>
      <View style={styles.barInner}>{props.children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { position: 'absolute', bottom: 0, left: 0, right: 0, borderTopWidth: StyleSheet.hairlineWidth, alignItems: 'center' },
  barInner: { flexDirection: 'row', width: '100%', maxWidth: MaxContentWidth, paddingVertical: Spacing.two },
  tab: { flex: 1, alignItems: 'center', paddingVertical: Spacing.two, borderRadius: Radius.md },
  tabText: { fontSize: 14, fontWeight: '600' },
});
