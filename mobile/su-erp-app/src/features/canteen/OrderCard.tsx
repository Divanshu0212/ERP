import type { Order } from '@api-types/index';
import { router } from 'expo-router';
import { Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { Button, Card, Label } from '@/components/ui';

import { ORDER_STAGES, ORDER_STATUS_COPY, isActive } from './useOrders';

const TERMINAL_STYLE: Record<string, string> = {
  completed: 'text-ink-muted',
  cancelled: 'text-critical',
};

export function OrderCard({ order, className = '' }: { order: Order; className?: string }) {
  const active = isActive(order);
  const reached = ORDER_STAGES.indexOf(order.status);

  return (
    <Card className={`gap-3 ${active ? 'border-brand/30 bg-brand-wash' : ''} ${className}`}>
      <View className="flex-row items-center justify-between">
        {active ? (
          <Label>{ORDER_STATUS_COPY[order.status]}</Label>
        ) : (
          <Text className={`text-label uppercase ${TERMINAL_STYLE[order.status] ?? 'text-ink-muted'}`}>
            {ORDER_STATUS_COPY[order.status]}
          </Text>
        )}
        <Money value={order.total} className="text-body font-semibold text-ink" />
      </View>

      {/* Three segments beat a spinner: the student can see how far along the
          kitchen is and roughly when to walk over. */}
      {active ? (
        <View className="flex-row gap-1.5">
          {ORDER_STAGES.map((stage, index) => (
            <View
              key={stage}
              className={`h-1 flex-1 rounded-full ${index <= reached ? 'bg-brand' : 'bg-surface-border'}`}
            />
          ))}
        </View>
      ) : null}

      <Text className="text-detail text-ink-muted">
        {order.items.map((i) => `${i.quantity}x ${i.name}`).join(', ')}
      </Text>

      <Text className="text-detail text-ink-faint">
        {new Date(order.created_at).toLocaleString([], {
          day: 'numeric',
          month: 'short',
          hour: 'numeric',
          minute: '2-digit',
        })}
      </Text>

      {/* Offered only once the food is actually ready — a code shown any
          earlier is one the counter cannot scan. */}
      {order.status === 'ready' ? (
        <Button
          label="Show pickup code"
          onPress={() => router.push('/(student)/pickup')}
        />
      ) : null}
    </Card>
  );
}
