import type { ReactNode } from 'react';
import { ActivityIndicator, Text, View, type ViewProps } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Press } from './Press';

export function Screen({ children }: { children: ReactNode }) {
  return (
    <SafeAreaView edges={['top']} className="flex-1 bg-surface-sunken">
      {children}
    </SafeAreaView>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return <Text className="text-title font-semibold text-ink">{children}</Text>;
}

export function Label({ children }: { children: ReactNode }) {
  return <Text className="text-label uppercase text-ink-faint">{children}</Text>;
}

export function Body({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return <Text className={muted ? 'text-body text-ink-muted' : 'text-body text-ink'}>{children}</Text>;
}

export function Card({ children, className = '', ...props }: ViewProps & { className?: string }) {
  return (
    <View
      className={`rounded-card border border-surface-border bg-surface p-4 ${className}`}
      {...props}
    >
      {children}
    </View>
  );
}

type Tone = 'brand' | 'critical' | 'quiet';

const TONE: Record<Tone, { box: string; text: string }> = {
  brand: { box: 'bg-brand', text: 'text-white' },
  critical: { box: 'bg-critical', text: 'text-white' },
  quiet: { box: 'bg-surface border border-surface-border', text: 'text-ink' },
};

export function Button({
  label,
  onPress,
  tone = 'brand',
  busy,
  disabled,
}: {
  label: string;
  onPress: () => void;
  tone?: Tone;
  busy?: boolean;
  disabled?: boolean;
}) {
  const styles = TONE[tone];
  return (
    <Press
      onPress={onPress}
      disabled={disabled || busy}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={{ minHeight: 48 }}
    >
      <View className={`min-h-touch items-center justify-center rounded-control px-4 ${styles.box}`}>
        {busy ? (
          <ActivityIndicator color={tone === 'quiet' ? '#16181d' : '#ffffff'} />
        ) : (
          <Text className={`text-body font-semibold ${styles.text}`}>{label}</Text>
        )}
      </View>
    </Press>
  );
}

/**
 * One component for the three states a fetched list can be in, so no screen
 * invents its own wording for "nothing here yet".
 */
export function ListState({
  loading,
  error,
  empty,
  onRetry,
}: {
  loading?: boolean;
  error?: string | null;
  empty: string;
  onRetry?: () => void;
}) {
  if (loading) {
    return (
      <View className="items-center gap-3 p-10">
        <ActivityIndicator color="#2c3ea8" />
        <Body muted>Loading</Body>
      </View>
    );
  }

  if (error) {
    return (
      <View className="items-center gap-3 p-10">
        <Body>{error}</Body>
        {onRetry ? <Button label="Try again" tone="quiet" onPress={onRetry} /> : null}
      </View>
    );
  }

  return (
    <View className="items-center p-10">
      <Body muted>{empty}</Body>
    </View>
  );
}
