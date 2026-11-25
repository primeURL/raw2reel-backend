/** First run: three swipe cards that explain the app in one breath, then never again. */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useRef, useState } from 'react';
import { type NativeScrollEvent, type NativeSyntheticEvent, ScrollView, type ScrollViewInstance, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

const KEY = 'raw2reel.onboarded.v1';

const CARDS = [
  { icon: '🎬', title: 'Drop in your raw clips', body: 'Shoot on your phone like always. Raw2Reel finds your best take and cuts the pauses and retakes.' },
  { icon: '🎨', title: 'Pick a look, or teach it one', body: 'Choose a look, or paste reels you love. It learns how they are edited, never what is in them.' },
  { icon: '✅', title: 'Approve every part', body: 'Captions, zooms, effects and sounds are added for you. Change anything, then export.' },
];

/** null while checking storage; true when the cards should show. */
export function useOnboarding() {
  const [show, setShow] = useState<boolean | null>(null);
  useEffect(() => {
    AsyncStorage.getItem(KEY).then((v) => setShow(v !== '1')).catch(() => setShow(false));
  }, []);
  const done = () => {
    setShow(false);
    AsyncStorage.setItem(KEY, '1').catch(() => {});
  };
  return { show, done };
}

export function Onboarding({ name, onDone }: { name: string | null; onDone: () => void }) {
  const t = useTheme();
  const { width } = useWindowDimensions();
  const scroll = useRef<ScrollViewInstance>(null);
  const [page, setPage] = useState(0);
  const last = page === CARDS.length - 1;
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => setPage(Math.round(e.nativeEvent.contentOffset.x / width));
  const next = () => (last ? onDone() : scroll.current?.scrollTo({ x: (page + 1) * width, animated: true }));

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: t.background }]}>
      <View style={styles.top}>
        <Text style={[styles.logo, { color: t.text }]}>Raw<Text style={{ color: t.accent }}>2</Text>Reel</Text>
        {!last ? <Button label="Skip" kind="ghost" style={styles.skip} onPress={onDone} /> : null}
      </View>
      <ScrollView ref={scroll} horizontal pagingEnabled showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onScroll} onScroll={onScroll} scrollEventThrottle={64}>
        {CARDS.map((c, i) => (
          <View key={c.title} style={[styles.page, { width }]}>
            <View style={[styles.art, { backgroundColor: t.backgroundElement, borderColor: t.border }]}>
              <Text style={styles.icon}>{c.icon}</Text>
              <Text style={[styles.step, { color: t.accent }]}>Step {i + 1} of {CARDS.length}</Text>
            </View>
            <Text style={[styles.title, { color: t.text }]}>{i === 0 && name ? `Hi ${name.split(' ')[0]}. ` : ''}{c.title}</Text>
            <Text style={[styles.body, { color: t.textSecondary }]}>{c.body}</Text>
          </View>
        ))}
      </ScrollView>
      <View style={styles.bottom}>
        <View style={styles.dots}>
          {CARDS.map((c, i) => (
            <View key={c.title} style={[styles.dot, { backgroundColor: i === page ? t.accent : t.border, width: i === page ? 22 : 8 }]} />
          ))}
        </View>
        <Button label={last ? "Let's start" : 'Next'} onPress={next} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: Spacing.four, height: 56 },
  logo: { fontSize: 22, fontWeight: '800', letterSpacing: -0.5 },
  skip: { minHeight: 36, paddingHorizontal: Spacing.two },
  page: { padding: Spacing.four, justifyContent: 'center', gap: Spacing.three, maxWidth: 560, alignSelf: 'center' },
  art: { aspectRatio: 1, maxHeight: 320, width: '100%', alignSelf: 'center', borderRadius: Radius.lg + 12, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center', gap: Spacing.three },
  icon: { fontSize: 96 },
  step: { fontSize: 13, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1 },
  title: { fontSize: 30, fontWeight: '800', letterSpacing: -0.5 },
  body: { fontSize: 17, lineHeight: 24 },
  bottom: { padding: Spacing.four, gap: Spacing.four },
  dots: { flexDirection: 'row', gap: Spacing.one, justifyContent: 'center' },
  dot: { height: 8, borderRadius: 4 },
});
