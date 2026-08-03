module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      // reanimated:false stops the preset injecting the worklets babel plugin.
      // react-native-worklets ships a native libworklets.so inside Expo Go that
      // segfaults this app on launch (SIGSEGV on mqt_v_js); the package is only
      // present because expo-router pulls it as an optional peer, and nothing
      // here uses it. Motion runs on RN core Animated instead — see src/design/motion.ts.
      ['babel-preset-expo', { jsxImportSource: 'nativewind', reanimated: false }],
      'nativewind/babel',
    ],
  };
};
