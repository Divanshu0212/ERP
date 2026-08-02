import { useEffect, useRef } from 'react';
import { AccessibilityInfo, Animated, Text, View } from 'react-native';

import { DURATION, EASE_OUT, useReduceMotion } from '@/design/motion';
import { useConnectivity } from '@/lib/net/connectivity';

function stampFor(cachedAt: number | undefined): string | null {
  if (!cachedAt) return null;

  const minutes = Math.floor((Date.now() - cachedAt) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;

  return new Date(cachedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/**
 * A persistent state, not a transient event, so this is an inline bar rather
 * than a snackbar — it has to stay visible for as long as it is true.
 *
 * It names the age of what is on screen because "offline" alone leaves the
 * student guessing whether the dues figure they are reading is from a minute
 * ago or from yesterday. A relative stamp answers that faster than a clock
 * time does.
 */
export function OfflineBanner({ cachedAt }: { cachedAt?: number }) {
  const online = useConnectivity((s) => s.online);
  const reduceMotion = useReduceMotion();
  const shift = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (online) return;

    // Announce it: the bar is a visual cue only, and a student using TalkBack
    // otherwise has no idea the screen went stale.
    AccessibilityInfo.announceForAccessibility('You are offline. Showing saved data.');
  }, [online]);

  useEffect(() => {
    shift.setValue(online ? 0 : 1);
  }, [online, shift]);

  useEffect(() => {
    if (online || reduceMotion) return;

    shift.setValue(0);
    Animated.timing(shift, {
      toValue: 1,
      duration: DURATION.slow,
      easing: EASE_OUT,
      useNativeDriver: true,
    }).start();
  }, [online, reduceMotion, shift]);

  if (online) return null;

  const stamp = stampFor(cachedAt);

  return (
    <Animated.View
      accessibilityRole="alert"
      style={{
        opacity: shift,
        transform: [
          {
            translateY: shift.interpolate({ inputRange: [0, 1], outputRange: [-12, 0] }),
          },
        ],
      }}
    >
      <View className="flex-row items-center gap-2 bg-caution-wash px-4 py-2.5">
        <View className="h-2 w-2 rounded-full bg-caution" />
        <Text className="flex-1 text-detail text-caution">
          {stamp ? `Offline — showing data from ${stamp}` : 'Offline — showing saved data'}
        </Text>
      </View>
    </Animated.View>
  );
}
