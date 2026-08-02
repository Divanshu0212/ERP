# SU-ERP

Multi-tenant ERP for institutions. Django microservices behind a gateway, Expo/React Native mobile app in `mobile/su-erp-app`.

## Design skills — use these every session

Any frontend work in this repo — new screens, redesigns, component or token changes, motion, layout, copy in the UI — goes through these. Invoke them before writing UI code, not after.

- **`impeccable`** (plugin skill) — the primary design skill. Sub-commands: `polish`, `audit`, `critique`, `animate`, `layout`, `typeset`, `clarify`, `harden`. It has native-specific references (`audit.native.md`, `adapt.native.md`, `android.md`) — use those for the mobile app, not the web ones.
- **`design-taste-frontend`** — taste and anti-slop direction. Web-oriented; translate its values rather than copying its CSS.
- **`improve-animations`** / **`review-animations`** / **`find-animation-opportunities`** — Emil Kowalski's motion skills. Advisory and read-only; they plan motion, they don't implement it. Also web-oriented, so translate to React Native.

The animation and taste skills assume the web platform. Their *values* (easing, duration, hierarchy, restraint) carry over; their APIs do not.

## Mobile constraints

**Never import `react-native-reanimated` or `react-native-worklets`.** Both are blocked at the Metro resolver in `mobile/su-erp-app/metro.config.js`. Expo Go ships its own prebuilt `libworklets.so`, and importing reanimated initializes that native runtime against a mismatched JS side, segfaulting the app on launch (SIGSEGV on `mqt_v_js`). The packages reappear in `node_modules` on any `npm install` because expo-router lists them as optional peers — that is expected and harmless as long as the resolver block stays. Removing the block needs a custom dev build, not Expo Go.

Motion uses RN core `Animated` with `useNativeDriver: true`, plus `LayoutAnimation`. Presets live in `src/design/motion.ts`.

**Styling is nativewind.** Design tokens live in `tailwind.config.js`; primitives in `src/components/ui.tsx` and `Press.tsx`. Screens use `className` and those primitives — no inline hex, no magic spacing numbers. Tokens are chosen for the real use scene: mid-range Android phones, one-handed, outdoors in daylight.

## Verification

Before claiming mobile work is done: `npx tsc --noEmit`, `npx jest`, and launch on the device over `adb reverse` (see `docs/RUNBOOK-mobile.md`). A passing bundle is not proof the app runs — this repo has had a build-clean, launch-crashing state before.

## Conventions

- Commit as `Divanshu0212 <divanshubhargava026@gmail.com>`. No Claude co-author trailer.
- Commit after every completed task rather than batching.
- Money fields arrive from DRF `DecimalField` as **strings**. Never do arithmetic without `Number()`.
- List endpoints return `{results, count, page, num_pages}`, not a bare array.
- Local machine cannot run every service at once — use compose profiles (default for demos; `full`/`observability` opt-in).
