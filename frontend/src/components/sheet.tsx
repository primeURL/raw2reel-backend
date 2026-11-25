/** Bottom sheet: slides up over the screen for one focused task (edit a caption, trim a part, export). */

import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { MaxContentWidth, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

export function Sheet({ open, onClose, title, children, footer }: {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <KeyboardAvoidingView style={styles.fill} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <Pressable style={[StyleSheet.absoluteFill, styles.backdrop]} onPress={onClose} accessibilityLabel="Close" />
        <View style={[styles.sheet, { backgroundColor: t.backgroundElement, borderColor: t.border, paddingBottom: Math.max(insets.bottom, Spacing.three) }]}>
          <View style={[styles.grab, { backgroundColor: t.border }]} />
          {title ? (
            <View style={styles.head}>
              <Text style={[styles.title, { color: t.text }]} numberOfLines={1}>{title}</Text>
              <Pressable onPress={onClose} hitSlop={12} accessibilityRole="button" accessibilityLabel="Close">
                <Text style={{ color: t.textSecondary, fontSize: 22 }}>×</Text>
              </Pressable>
            </View>
          ) : null}
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">{children}</ScrollView>
          {footer ? <View style={styles.footer}>{footer}</View> : null}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { backgroundColor: 'rgba(0,0,0,0.5)' },
  sheet: {
    width: '100%', maxWidth: MaxContentWidth, alignSelf: 'center', maxHeight: '88%',
    borderTopLeftRadius: Radius.lg + 8, borderTopRightRadius: Radius.lg + 8, borderWidth: StyleSheet.hairlineWidth,
  },
  grab: { width: 40, height: 5, borderRadius: 3, alignSelf: 'center', marginTop: Spacing.two },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: Spacing.four, paddingTop: Spacing.three },
  title: { fontSize: 19, fontWeight: '700', flex: 1 },
  body: { padding: Spacing.four, paddingTop: Spacing.three, gap: Spacing.three },
  footer: { flexDirection: 'row', gap: Spacing.two, paddingHorizontal: Spacing.four },
});
