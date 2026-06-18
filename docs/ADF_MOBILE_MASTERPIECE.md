# ADF Mobile — The Masterpiece Plan

> **Provenance.** Authored 2026-06-18 by a 4-expert design panel (mobile UX/design-system ·
> architecture/navigation · device capabilities · verification science → synthesis), every
> claim verified against the live repo on a Mac with `xcodebuild` + a booted iPhone 16
> simulator. This is the roadmap to make ADF the best-in-world builder of real Android/iOS
> apps. STATUS: MM6-core (policy honest on mobile) and MM1 (design system) are DONE +
> validated live; the rest (MM2 component kit, MM3 navigation, MM4 mobile shapes, MM7-9
> device capabilities, MM10-13 simulator/proof depth, MM14-15 signed store release) follow.

Confirmed: `dependency_allowlist` fails on the Expo template with violations for `@expo/metro-runtime`, `expo`, `react-native`, etc. Every claim in the brief is verified against the real code. I now have everything I need to write the masterpiece plan.

I have verified every load-bearing claim against the actual repo. Here is the masterpiece plan.

---

# ADF Mobile: The Masterpiece Plan

*Verified against the live repo at `/Users/varunkumar/ai_pos_system/adf-framework` on this Mac (xcodebuild present, iPhone 16e booted, `eas`/`gradle` absent). Every file/line citation below was read or executed, not assumed.*

## 1. The masterpiece thesis

ADF today proves a **single-screen, theme-less, capability-less** RN app renders as web DOM and seals a Merkle proof — real, but a toy-grade product. The leap to best-in-world is four moves landed *through the existing moat, never around it*: (1) **multi-screen** via Expo Router (file-based `app/` routes that render on web through the same `expo export -p web` path and emit `role="tab"/"link"` that `visual_verify` already counts); (2) a **real design system** — token layer + light/dark + an Icon and the 6 native-feel components — so apps are on-theme *by construction* and provably so; (3) **native device capabilities** (image-pick, local notifications, secure-store) wired with mandatory web fallbacks so the render gate still proves them; (4) **verification on a real iOS Simulator** (the booted iPhone 16e answers `simctl io booted screenshot` now). The unifying discipline: every new capability adds a *sealed* fact to the Proof of Build (on-theme, render-target, declared permissions, bundle budget), so "feels native" becomes a cryptographically attested property — something no competitor's render gate does.

## 2. Capability scorecard

| Capability | Have today (verified) | Masterpiece bar | Gap |
|---|---|---|---|
| **Navigation / multi-screen** | `App.tsx` → one `Screen` → one feature. No router, no `app/` dir, no back/tabs. | Expo Router: root Stack + bottom Tabs + list→detail push; multi-screen by default. | **Total.** No nav layer exists. #1 gap. |
| **Design system / theme** | Inline hex in all 4 primitives (`Button #2563eb`, `Input #d1d5db`, `Card #e5e7eb`, `Screen #f9fafb`). No tokens, no dark mode. | `src/theme` token source-of-truth, `useTheme()` reading `useColorScheme()`, light+dark, no raw hex. | **Total**, but **zero new deps** (`useColorScheme`/`Appearance` in RN core). |
| **Component kit** | 4 primitives (Button/Input/Card/Screen). No Icon, Header, ListItem, TabBar, Badge, EmptyState, List/FlatList wrapper. | ~10 native-feel components, theme-consuming, a11y-annotated, auto-picked by `component_manifest`. | **Large.** `@expo/vector-icons` ships with SDK 51 (no new dep for Icon). |
| **Feature shapes (mobile-native)** | `SHAPES = (crud-list, auth, form, dashboard, single-record)` — web-derived; `_CONTRACTS` reference `server/api/` routes that don't exist on mobile. | tab-app, list-detail, feed, profile, onboarding, search-filter — each pins `app/` routes + hooks + kit composition. | **Large.** Blocked by a test (see §4) and by missing nav. |
| **Device capabilities** | **Zero.** No camera/photos/location/notifications/secure-store/haptics. | Curated capability seam: typed hook + affordance + permission + mandatory web fallback, opt-in per spec. | **Total**, and **policy gate currently fails on the Expo template** (verified: `dependency_allowlist` ok=False). |
| **Verification depth** | tsc + jest + **web** render gate (`react-native-web` DOM). `_expo_native_stage` only checks a toolchain *exists*, then returns a happy string — never boots a sim. | + iOS-Simulator render rung (cheap WebKit-on-sim now; native `expo run:ios` opt-in). | **High.** Booted iPhone 16e is idle; `simctl screenshot` works today. |
| **The proof** | `_verdict_bytes` seals `{stack, verified, verify_summary, policy}` only. | + sealed `render.platforms / render_proven / permissions / perf(js_bytes,render_ms)`. | **Medium.** Bundle size (383,454 B) is produced free and discarded. |

## 3. The masterpiece roadmap

Leverage/effort per node; deps in brackets. Groups are layered — A is the foundation everything else composes on.

**(A) Polished + multi-screen — the foundation**
- **MM1 — Theme tokens + light/dark `ThemeProvider`, primitives refactored, render-gate proves on-theme.** `[none]` — **critical / medium.** Zero new deps. Keystone: Icon/ListItem/Header/no-raw-hex all depend on a token layer existing.
- **MM2 — Icon primitive (`@expo/vector-icons` Ionicons) + the 6 native-feel components** (Header, ListItem, TabBar, Badge, EmptyState, List/FlatList wrapper). `[MM1]` — **critical / large.** Unblocks every native screen.
- **MM3 — Expo Router (`app/` Stack+Tabs) + a `list-detail` mobile shape.** `[MM2]` — **critical / medium.** Breaks the single-screen ceiling; renders on web through the *existing* gate (Tabs/Link → `role="tab"/"link"`, already in `_INTERACTIVE_ROLES`).
- **MM4 — Mobile-native shapes (tab-app, feed, profile, onboarding, search-filter) + stack-aware `contract_for` + completion audit `_M_NAV`.** `[MM3]` — **high / large.** Requires the test split in §4.
- **MM5 — Prompt + moat tightening:** `_expo_build_messages` enumerates the kit + forbids hardcoded hex; `policy_gate` `_check_no_raw_hex`; `expected_dom` adds `headings≥1`; `links` counter in `_BodyStats`. `[MM1–MM4]` — **high / medium.**

**(B) Native device capabilities**
- **MM6 — Stack-aware policy allowlist + curated expo capability set + native-permission rule (reads `app.json`).** `[none, but unblocks all of B]` — **critical / small→medium.** *Required first:* `check_policy(templates/expo-rn)` returns **ok=False** today — the mobile moat is dishonest until this lands.
- **MM7 — Capability seam in `feature_shapes` + first capability: image-pick (`expo-image-picker`).** `[MM6]` — **high / medium.** Web fallback = `<input type=file>` (real DOM the gate sees).
- **MM8 — Local notifications (`expo-notifications`, local-only).** `[MM7]` — **high / medium.**
- **MM9 — secure-store + biometrics wired into the `auth` shape.** `[MM7]` — **high / medium.** Proves the token never sits in plaintext.

**(C) Deepen verification to real devices**
- **MM10 — iOS-Simulator render rung** (`native_render.py`: reuse booted sim, serve `dist/`, `simctl io screenshot`, non-blank pixel assertion), sealed into proof. `[MM3 helpful]` — **high / large.** Buildable *now* on this Mac.
- **MM11 — Mobile-aware Proof of Build:** seal `platforms / render_proven / permissions / perf`. `[MM6, MM10]` — **critical / medium.**
- **MM12 — Bundle/cold-start budget sealed** (the 383,454 B is already on disk). `[MM11]` — **high / small.**
- **MM13 — A11y *name* audit** (`assess_dom` checks accessible names; fix `Input.tsx` to pass `accessibilityLabel`). `[MM1, MM5]` — **high / medium.**

**(D) Ship-to-store — infra-gated (honest: not buildable on this box)**
- **MM14 — `expo run:ios` true native render** (prebuild + xcodebuild + `simctl launch`), opt-in `ADF_MOBILE_NATIVE=strict`. `[MM10]` — **medium / large.** Slow; never on the default path.
- **MM15 — Signed `.ipa`/`.aab` via EAS + store submission.** `[external]` — **deferred.** `eas`/`gradle` **not installed** (verified). Requires accounts/credentials. Code already degrades gracefully.

## 4. THE FIRST NODE TO BUILD NOW (test-first) — MM1

**Theme tokens + light/dark `ThemeProvider`, the 4 primitives refactored to consume it, and a no-raw-hex policy check + `headings≥1` render assertion that make "on-theme" a *sealed* property.** Highest leverage-to-effort, **zero new dependencies** (`useColorScheme`+`Appearance` are in RN core, verified), self-contained to the template + two Python engines, and it stays green through tsc + jest + the live web-render gate.

### Deliverables

**Template (`templates/expo-rn/`):**
- `src/theme/tokens.ts` — `lightColors`/`darkColors` (bg, surface, surfaceAlt, text, textMuted, primary, onPrimary, border, danger, success, warning) + `spacing` (xs/sm/md/lg/xl = 4/8/12/16/24) + `radius` (sm/md/lg/full) + `type` (h1/h2/body/caption/label) + `iconSize` scale.
- `src/theme/ThemeProvider.tsx` — `ThemeProvider` + `useTheme()` returning `useColorScheme()==='dark' ? darkTheme : lightTheme`.
- `src/theme/index.ts` — barrel export.
- Refactor `Button.tsx`, `Input.tsx`, `Card.tsx`, `Screen.tsx` to `const t = useTheme()` and replace **all** inline hex with `t.colors.*`. **Preserve** `accessibilityRole="button"` on Button (the render gate keys on it, `visual_verify.py:84`). Mount `ThemeProvider` in `Screen.tsx`.
- `src/components/ui/Text.tsx` — semantic `Text` variants (h1/h2/body/caption/label) reading `t.type.*`; export from `ui/index.ts`. Replace the ad-hoc `App.tsx` inline `h1` (`fontSize:24/'800'`).
- `__tests__/theme.test.tsx` — render the kit under mocked light **and** dark schemes.

**Engines:**
- `scripts/orch/policy_gate.py` — add `_check_no_raw_hex(files)` = `re.compile(r'#[0-9a-fA-F]{3,8}\b')` scoped to `src/**.tsx` **excluding `src/theme/**`**; register in `_CHECKS` + `DEFAULT_POLICY['rules']` + surface in `policy_summary`.
- `scripts/orch/feature_shapes.py` — add `"headings": 1` to `crud-list/form/single-record/auth` in `_EXPECTED_DOM` (lands together with the Header expectation so generation can satisfy it).
- `scripts/orch/agent_runner.py` — `_expo_build_messages`: add a fixed UI-KIT block referencing `src/theme` + `useTheme()` and a hard rule "Do NOT call `StyleSheet.create` with literal hex — use theme tokens."

### RED test plan (must fail before, pass after; tsc+jest+web-render stay green)

1. **`test_policy_gate.py::test_raw_hex_in_component_fails`** — a synthetic `src/components/Foo.tsx` containing `backgroundColor: '#2563eb'` makes `check_policy()` return a `no_raw_hex` violation; a token-only file passes; a `src/theme/tokens.ts` with hex does **not** trip it (whitelist). *RED today: no such check exists.*
2. **`templates/expo-rn/__tests__/theme.test.tsx`** — mock `useColorScheme → 'dark'`, `render(<Screen><Button title="x"/></Screen>)`; assert resolved `Screen` bg `=== darkColors.bg` and `Button` bg `=== darkColors.primary`. *RED today: no `useTheme`; primitives hardcode light hex.*
3. **`test_feature_shapes.py::test_expected_dom_requires_heading`** — `expected_dom('crud-list')` includes `headings >= 1`. *RED until added.*
4. **`test_visual_verify.py::test_check_expected_dom_flags_missing_heading`** — `check_expected_dom({...,'headings':0}, {'headings':1})` returns `(False, [...])`. *Confirms the gate proves a Header rendered.*
5. **GREEN regression (the moat must carry):** existing `tsc --noEmit` + `jest` + `_expo_web_render` still pass after the refactor — the app still emits real DOM through `react-native-web`. Run: `npm run typecheck && npm test && npm run web:export` in `templates/expo-rn`, then the headless render gate asserts `rendered=True`.

**Sequencing caution (verified risk):** adding `headings≥1` to `expected_dom` will (correctly) start failing any generated app with no Header. Land it **with** the Header component (MM2) and the prompt rule (MM5) — or scope MM1's `headings` change to only assert in the render audit once a Header primitive exists — so existing golden apps don't go red prematurely.

## 5. Honest reality check

**Genuinely buildable now, on this box, $0, no new infra:**
- **MM1 entirely** — `useColorScheme`/`Appearance` are in RN core; refactor + tests + policy/render-gate changes are pure local Python + template edits, all covered by existing CI (`test_feature_shapes`, `test_visual_verify`, `test_policy_gate`, `test_agent_runner`).
- **MM2/MM3/MM6/MM7** — Icon (`@expo/vector-icons` ships with SDK 51), Expo Router (renders on web via the same `expo export -p web` path; `jest.config` already whitelists react-navigation), the policy allowlist fix, and image-pick (web fallback = file input). All verifiable through the **existing** web-render gate.
- **MM10 (cheap rung)** — the iPhone 16e is **booted right now** and `simctl io booted screenshot` returns a real PNG. Serving `dist/` to Mobile Safari on the sim + a non-blank-pixel assertion is a *seconds*-long real-iOS-target render.

**Needs the user's infra / accounts (correctly deferred):**
- **True native RN render** (`expo run:ios` → prebuild + CocoaPods + xcodebuild): buildable here but minutes-long and flake-prone → opt-in `ADF_MOBILE_NATIVE=strict`, never on the default path (MM14).
- **Signed `.ipa`/`.aab` + store submission:** `eas` and `gradle` are **not installed** (verified) → external EAS account + Apple/Google credentials (MM15). Push notifications need APNs/FCM; `react-native-maps` needs a Google Maps key (the `no_secrets` rule would flag it) — both deliberately out of wave 1.

**The honesty bug to fix first (MM6):** `check_policy(templates/expo-rn)` returns **ok=False today** — `dependency_allowlist` flags `expo`, `react-native`, `@expo/metro-runtime`, etc. against the hardcoded react-vite allowlist (`policy_gate.py:27`). Every Expo app is currently "verified but policy-non-compliant." This must be made stack-aware before any device capability can ship "provably."

**Cheapest measurable proof the direction works:** land MM1 and show the diff in the sealed verdict — a generated app now (a) renders identical DOM under mocked dark scheme, (b) **cannot** seal green if it hardcodes a hex color (`no_raw_hex` RED→GREEN), and (c) **cannot** seal green if it renders no heading (`headings≥1` RED→GREEN) — all while tsc + jest + the live web-render gate stay green. That is a one-node, fully-local demonstration that "on-theme + has-a-header" became a *cryptographically sealed* property of the Proof of Build, with the moat deepened rather than bypassed.

---

**Key files (all absolute):**
- `/Users/varunkumar/ai_pos_system/adf-framework/templates/expo-rn/src/components/ui/{Button,Input,Card,Screen,index}.tsx`, `App.tsx`, `app.json`, `package.json`
- `/Users/varunkumar/ai_pos_system/adf-framework/scripts/orch/feature_shapes.py` (`SHAPES`:25, `_CONTRACTS`:110, `_EXPECTED_DOM`:218, `contract_for`:232 — note: **no `stack` param today**)
- `/Users/varunkumar/ai_pos_system/adf-framework/scripts/orch/visual_verify.py` (`_INTERACTIVE_ROLES`:54, `_BodyStats`:46, `check_expected_dom`:127)
- `/Users/varunkumar/ai_pos_system/adf-framework/scripts/orch/policy_gate.py` (`_DEFAULT_ALLOWLIST`:27 — react-vite set, **fails on Expo**; `_CHECKS`:201)
- `/Users/varunkumar/ai_pos_system/adf-framework/scripts/orch/agent_runner.py` (`_expo_build_messages`:455, `contract_for` call:489, `_native_toolchain`:1230, `_expo_native_stage`:1245 — **no-op string**, `_expo_web_render`:1262, `_AUDIT_REQUIRED_MOBILE`:1644, `_audit_render`:1709)
- `/Users/varunkumar/ai_pos_system/adf-framework/scripts/orch/proof_of_build.py` (`_verdict_bytes`:59 — seals only `{stack,verified,verify_summary,policy}`)
- `/Users/varunkumar/ai_pos_system/adf-framework/scripts/orch/test_feature_shapes.py:83` — **blocking test debt**: asserts every contract contains `server/api/` (must split web vs mobile before adding mobile shapes).