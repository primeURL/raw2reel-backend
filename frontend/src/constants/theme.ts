/**
 * Raw2Reel colours. Dark is the main look (videos read best on dark); light mirrors it.
 * Accent orange matches the reels' accent (#FF5A1F) so the app and the videos feel like one brand.
 */

import '@/global.css';

import { Platform } from 'react-native';

export const Accent = '#FF5A1F';

export const Colors = {
  light: {
    text: '#111113',
    background: '#FAFAF9',
    backgroundElement: '#F0EFEC',
    backgroundSelected: '#E4E2DD',
    textSecondary: '#6B6A67',
    border: '#E2E0DB',
    accent: Accent,
    onAccent: '#FFFFFF',
    danger: '#D93025',
    success: '#1E8E3E',
  },
  dark: {
    text: '#F5F4F1',
    background: '#0E0E10',
    backgroundElement: '#1A1A1D',
    backgroundSelected: '#26262A',
    textSecondary: '#A09F9B',
    border: '#2A2A2E',
    accent: Accent,
    onAccent: '#FFFFFF',
    danger: '#FF6B5E',
    success: '#5BD17A',
  },
} as const;

export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;

export const Fonts = Platform.select({
  ios: {
    sans: 'system-ui',
    serif: 'ui-serif',
    rounded: 'ui-rounded',
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: 'var(--font-display)',
    serif: 'var(--font-serif)',
    rounded: 'var(--font-rounded)',
    mono: 'var(--font-mono)',
  },
});

export const Spacing = {
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
} as const;

export const Radius = { sm: 8, md: 12, lg: 16, pill: 999 } as const;

export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;
export const MaxContentWidth = 800;
