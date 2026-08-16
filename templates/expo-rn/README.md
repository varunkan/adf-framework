# ADF Expo / React Native template (`expo-rn`)

A checked-in, working cross-platform mobile app (iOS + Android + web) that ADF
scaffolds, then the model emits ONLY the feature's files (scaffold-then-diff).

- **One codebase → iOS + Android + web** (Expo + React Native + react-native-web).
- **Local persistence** via `expo-sqlite` (`src/db.ts`) — the app is self-contained,
  no server.
- **UI primitives** in `src/components/ui/` (`Button`, `Input`, `Card`, `Screen`) —
  props-driven, with `accessibilityRole` so they render-verify on web.
- **Verified the ADF way**: `tsc --noEmit` + `jest` + a render-proof on the web
  export (`npm run web:export` → `serve-web.mjs`) + a sealed Proof of Build.

## Scripts
- `npm run typecheck` — `tsc --noEmit`
- `npm test` — jest (`@testing-library/react-native`)
- `npm run web:export` — static web bundle into `dist/`
- `npm run web:serve` — serve `dist/` on `$PORT` (ADF's live preview + render gate)
- `npm start` / `npm run ios` / `npm run android` — Expo dev (device/simulator)

Native device builds + store submission go through EAS (`eas build` / `eas submit`)
and require a Mac/Xcode + Android SDK + Apple/Google developer accounts.
