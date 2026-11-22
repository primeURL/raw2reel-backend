/**
 * Runtime config from EXPO_PUBLIC_* env vars (inlined at build time).
 *
 * EXPO_PUBLIC_API_URL   backend base URL. iOS simulator / web: http://localhost:8000.
 *                       A real phone needs your Mac's LAN IP, e.g. http://192.168.1.20:8000.
 * EXPO_PUBLIC_DEV_LOGIN "true" shows the dev sign-in (backend AUTH_DEV_BYPASS) until
 *                       Google sign-in is added. Never enable it in a store build.
 */

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '');

export const DEV_LOGIN = __DEV__ || process.env.EXPO_PUBLIC_DEV_LOGIN === 'true';
