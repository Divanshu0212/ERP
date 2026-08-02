const path = require('path');

const { getDefaultConfig } = require('expo/metro-config');
const { withNativeWind } = require('nativewind/metro');

const config = getDefaultConfig(__dirname);

/**
 * Keep Reanimated and Worklets out of the bundle entirely.
 *
 * Expo Go ships its own prebuilt libworklets.so. When anything in the graph
 * imports react-native-reanimated, that native runtime initializes against a
 * mismatched JS side and segfaults on launch: SIGSEGV on the mqt_v_js thread,
 * libworklets.so calling into Hermes' memcpy. Nothing in this app uses either
 * package — they arrive only because expo-router lists them as optional peers,
 * which is why `npm uninstall` does not keep them out (see commit fa140aa,
 * whose fix silently regressed on the next install).
 *
 * Bisected on a Motorola edge 50 fusion: bare RN and MMKV run clean, adding
 * expo-router reproduces the crash, and this block clears it.
 *
 * Removing this requires a custom dev build with matching native worklets,
 * not Expo Go. Motion runs on RN core Animated instead — see src/design/motion.ts.
 */
const BLOCKED = new Set(['react-native-reanimated', 'react-native-worklets']);
const stub = path.resolve(__dirname, 'src/design/empty-module.js');

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (BLOCKED.has(moduleName) || moduleName.startsWith('react-native-worklets/')) {
    return { type: 'sourceFile', filePath: stub };
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = withNativeWind(config, { input: './global.css' });
