import type { Order } from '@api-types/index';
import { View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { Body, Card, Label, ListState, Screen, Title } from '@/components/ui';
import {
  ORDER_STATUS_COPY,
  isActive,
  useOrders,
  usePickupToken,
} from '@/features/canteen/useOrders';

/**
 * The collection code for a ready order. Separate from the orders list
 * because at the counter the student needs one thing at phone-held-up size,
 * not a scrollable history.
 */
export default function PickupScreen() {
  const orders = useOrders();
  const active = (orders.data?.results ?? []).filter(isActive);
  const ready = active.find((order: Order) => order.status === 'ready') ?? null;
  const token = usePickupToken(ready?.id ?? null);

  return (
    <Screen>
      <View className="gap-4 p-4">
        <Title>Collect your order</Title>

        {orders.isLoading || active.length === 0 ? (
          <ListState
            loading={orders.isLoading}
            error={orders.isError ? 'Could not load your orders.' : null}
            empty="You have no order in progress."
            onRetry={() => void orders.refetch()}
          />
        ) : ready && token.data ? (
          <Card className="items-center gap-4 py-8">
            {/* White quiet zone: counter scanners fail against a tinted background. */}
            <View className="rounded-card bg-surface p-4">
              <QRCode value={token.data.token} size={260} backgroundColor="#ffffff" color="#16181d" />
            </View>
            <View className="items-center gap-1">
              <Label>Show this at the counter</Label>
              <Body muted>Scanning it completes your order.</Body>
            </View>
          </Card>
        ) : (
          <Card className="gap-2">
            <Label>{ORDER_STATUS_COPY[active[0].status]}</Label>
            {/* Named plainly: the student is waiting and wants to know what for. */}
            <Body muted>
              Your collection code appears here the moment the kitchen marks your order ready.
            </Body>
          </Card>
        )}
      </View>
    </Screen>
  );
}
