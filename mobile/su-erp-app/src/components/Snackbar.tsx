import { useEffect, useRef, useState } from 'react';
import { Animated, Text, View } from 'react-native';

import { DURATION, EASE_OUT, useReduceMotion } from '@/design/motion';

export interface SnackMessage {
  text: string;
  tone?: 'neutral' | 'critical';
}

/**
 * Material's transient feedback surface. Used instead of Alert for outcomes
 * the student does not have to acknowledge — a modal that must be dismissed
 * to keep going is an interruption, and paying a fee or filing a complaint
 * should not end in one.
 */
export function Snackbar({ message, onDone }: { message: SnackMessage | null; onDone: () => void }) {
  const reduceMotion = useReduceMotion();
  const rise = useRef(new Animated.Value(0)).current;
  const [shown, setShown] = useState<SnackMessage | null>(null);

  useEffect(() => {
    if (!message) return;

    setShown(message);
    rise.setValue(reduceMotion ? 1 : 0);

    if (!reduceMotion) {
      Animated.timing(rise, {
        toValue: 1,
        duration: DURATION.base,
        easing: EASE_OUT,
        useNativeDriver: true,
      }).start();
    }

    const timer = setTimeout(() => {
      setShown(null);
      onDone();
    }, 4000);

    return () => clearTimeout(timer);
  }, [message, reduceMotion, rise, onDone]);

  if (!shown) return null;

  return (
    <Animated.View
      accessibilityRole="alert"
      pointerEvents="none"
      style={{
        position: 'absolute',
        left: 12,
        right: 12,
        bottom: 16,
        opacity: rise,
        transform: [{ translateY: rise.interpolate({ inputRange: [0, 1], outputRange: [16, 0] }) }],
      }}
    >
      <View
        className={`rounded-control px-4 py-3 ${shown.tone === 'critical' ? 'bg-critical' : 'bg-ink'}`}
      >
        <Text className="text-body text-white">{shown.text}</Text>
      </View>
    </Animated.View>
  );
}

/** Small helper so screens do not each reinvent the show/clear pair. */
export function useSnackbar() {
  const [message, setMessage] = useState<SnackMessage | null>(null);

  return {
    message,
    clear: () => setMessage(null),
    show: (text: string, tone: SnackMessage['tone'] = 'neutral') => setMessage({ text, tone }),
  };
}
