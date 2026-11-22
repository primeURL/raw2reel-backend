/**
 * Who is signed in. Today: the dev sign-in (backend AUTH_DEV_BYPASS, token "dev:<id>").
 * Google sign-in via Firebase plugs in here later: it produces a Firebase ID token and calls
 * the same signIn(token) - nothing else in the app changes.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient } from '@tanstack/react-query';
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { api, configureApi } from './api';
import type { Me } from './types';

const KEY = 'raw2reel.session.token';

interface Session {
  ready: boolean; // finished reading the saved token
  token: string | null;
  me: Me | null;
  signInDev: (userId: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const tokenRef = useRef<string | null>(null);

  const signOut = useCallback(async () => {
    tokenRef.current = null;
    setToken(null);
    setMe(null);
    queryClient.clear();
    await AsyncStorage.removeItem(KEY).catch(() => {});
  }, [queryClient]);

  const signIn = useCallback(async (newToken: string) => {
    const user = await api.me(newToken); // throws if the server rejects it
    tokenRef.current = newToken;
    setToken(newToken);
    setMe(user);
    await AsyncStorage.setItem(KEY, newToken).catch(() => {});
  }, []);

  const signInDev = useCallback((userId: string) => signIn(`dev:${userId.trim()}`), [signIn]);

  useEffect(() => {
    configureApi(() => tokenRef.current, () => void signOut());
  }, [signOut]);

  // restore the saved session on launch
  useEffect(() => {
    (async () => {
      const saved = await AsyncStorage.getItem(KEY).catch(() => null);
      if (saved) {
        try {
          await signIn(saved);
        } catch {
          await AsyncStorage.removeItem(KEY).catch(() => {});
        }
      }
      setReady(true);
    })();
  }, [signIn]);

  const value = useMemo(() => ({ ready, token, me, signInDev, signOut }), [ready, token, me, signInDev, signOut]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error('useSession must be used inside SessionProvider');
  return s;
}
