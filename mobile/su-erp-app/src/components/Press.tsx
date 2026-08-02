import type { ReactNode } from 'react';
import { useRef } from 'react';
import { Animated, Pressable, type PressableProps, type ViewStyle } from 'react-native';

import { DURATION, EASE_OUT, PRESS_SCALE } from '@/design/motion';

/**
 * A Pressable that dips under the finger. Touch has no hover state to tell
 * you a target is live, so the press itself has to answer.
 */
export function Press({
  children,
  style,
  disabled,
  ...props
}: Omit<PressableProps, 'children' | 'style'> & { children?: ReactNode; style?: ViewStyle }) {
  const scale = useRef(new Animated.Value(1)).current;

  const to = (value: number, duration: number) =>
    Animated.timing(scale, {
      toValue: value,
      duration,
      easing: EASE_OUT,
      useNativeDriver: true,
    }).start();

  return (
    <Pressable
      disabled={disabled}
      onPressIn={() => to(PRESS_SCALE, DURATION.instant)}
      onPressOut={() => to(1, DURATION.base)}
      {...props}
    >
      <Animated.View style={[style, { transform: [{ scale }], opacity: disabled ? 0.45 : 1 }]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}
