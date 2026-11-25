/**
 * Runtime config from EXPO_PUBLIC_* env vars (inlined at build time).
 *
 * EXPO_PUBLIC_API_URL   backend base URL for a deployed server (https://…).
 *                       In development it can be left out: the app talks to port 8000 on the
 *                       same computer it loaded from (Expo's own address), so it keeps working
 *                       when the Wi-Fi gives the Mac a new IP.
 * EXPO_PUBLIC_DEV_LOGIN "true" shows the dev sign-in (backend AUTH_DEV_BYPASS) until
 *                       Google sign-in is added. Never enable it in a store build.
 */

import Constants from 'expo-constants';
import { Platform } from 'react-native';

const DEV_API_PORT = 8000;

/** The computer running Expo, as the phone sees it (e.g. 192.168.0.4), in development only. */
function devHost(): string | null {
  if (!__DEV__) return null;
  if (Platform.OS === 'web') return typeof window !== 'undefined' ? window.location.hostname : null;
  const uri = Constants.expoConfig?.hostUri ?? Constants.linkingUri ?? '';
  const host = uri.replace(/^[a-z]+:\/\//, '').split('/')[0].split(':')[0];
  // a tunnel address (exp.direct) doesn't lead to our API: fall back to the env URL then
  if (!host || host.endsWith('.exp.direct')) return null;
  return host;
}

function apiUrl(): string {
  const fromEnv = (process.env.EXPO_PUBLIC_API_URL ?? '').replace(/\/+$/, '');
  if (fromEnv.startsWith('https://')) return fromEnv; // a deployed server always wins
  const host = devHost();
  if (host) return `http://${host}:${DEV_API_PORT}`;
  return fromEnv || `http://localhost:${DEV_API_PORT}`;
}

export const API_URL = apiUrl();

export const DEV_LOGIN = __DEV__ || process.env.EXPO_PUBLIC_DEV_LOGIN === 'true';
