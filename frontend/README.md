# Raw2Reel app (Expo SDK 58, React Native, Expo Router)

```bash
nvm use 22            # Node 22 (see .nvmrc)
cp .env.example .env  # EXPO_PUBLIC_API_URL -> the backend
npm install
npx expo start        # i = iOS simulator, a = Android, w = web
npm run typecheck && npx expo lint
```

The backend must be running (`../backend`, `docker compose up -d`). On a real phone set
`EXPO_PUBLIC_API_URL` to your Mac's LAN IP (`ipconfig getifaddr en0`), not localhost.

## Layout

| Path | What |
|---|---|
| `src/app/_layout.tsx` | providers (react-query, session, theme) and the sign-in gate |
| `src/app/index.tsx` · `styles.tsx` · `profile.tsx` | the three tabs |
| `src/components/app-tabs.tsx` / `.web.tsx` | native tabs (SF Symbols / Material icons) and the web tab bar |
| `src/components/sign-in.tsx` | sign-in screen (Google comes with Firebase; dev sign-in for now) |
| `src/lib/api.ts` · `types.ts` | typed API client (keep `types.ts` in sync with `backend/app/schemas.py`) |
| `src/lib/session.tsx` | who is signed in; token saved on the device |
| `src/constants/theme.ts` | colours (accent `#FF5A1F`), spacing, radius |

## Sign-in

Google sign-in via Firebase is not wired yet. In development the **developer sign-in** uses the
backend's `AUTH_DEV_BYPASS` (`Bearer dev:<id>`). Firebase will call the same `signIn(token)` in
`session.tsx` with a Firebase ID token.
