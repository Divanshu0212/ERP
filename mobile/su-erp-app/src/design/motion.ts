import { useEffect, useState } from 'react';
import { AccessibilityInfo, Easing, LayoutAnimation, Platform, UIManager } from 'react-native';

/**
 * Motion runs on RN core Animated rather than Reanimated: react-native-worklets
 * ships a native libworklets.so inside Expo Go that segfaults this project on
 * launch (SIGSEGV on mqt_v_js). Escaping that needs a custom dev build, not a
 * JS-side fix. Everything here uses useNativeDriver so it stays off the JS
 * thread anyway.
 */

/** Exponential ease-out: fast commit, soft landing. The house curve. */
export const EASE_OUT = Easing.bezier(0.16, 1, 0.3, 1);

/** For things leaving, which should not linger. */
export const EASE_IN = Easing.bezier(0.4, 0, 1, 1);

export const DURATION = {
  /** Press feedback and other direct-manipulation echoes. */
  instant: 110,
  /** The default for entrances and state changes. */
  base: 220,
  /** Banners and anything crossing a large distance. */
  slow: 320,
} as const;

/** Press-in scale. Deep enough to feel, shallow enough not to wobble. */
export const PRESS_SCALE = 0.97;

if (Platform.OS === 'android') {
  UIManager.setLayoutAnimationEnabledExperimental?.(true);
}

/**
 * Animates the next layout change — a list row arriving, a section expanding.
 * Call immediately before the state update that changes the layout.
 */
export function animateNextLayout(): void {
  LayoutAnimation.configureNext({
    duration: DURATION.base,
    create: { type: 'easeOut', property: 'opacity' },
    update: { type: 'easeInEaseOut' },
    delete: { type: 'easeIn', property: 'opacity' },
  });
}

/**
 * Tracks the system "Remove animations" setting. Material requires motion to
 * degrade to a crossfade or an instant cut when a user has asked for less of
 * it — for some people large movement is nausea, not delight.
 */
export function useReduceMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (active) setReduced(value);
    });

    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduced);
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  return reduced;
}
