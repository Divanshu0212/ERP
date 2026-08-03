import { FlatList, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { Body, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { OrderCard } from '@/features/canteen/OrderCard';
import { ORDERS_KEY, isActive, useOrders } from '@/features/canteen/useOrders';
import { cacheAge } from '@/lib/query/persister';

export default function OrdersScreen() {
  const { data, isLoading, isError, refetch, isRefetching } = useOrders();

  const orders = data?.results ?? [];
  const active = orders.filter(isActive);
  const past = orders.filter((o) => !isActive(o));

  // What the student actually spent, not what they ordered — a cancelled
  // order was never charged.
  const spent = orders
    .filter((o) => o.status === 'completed')
    .reduce((sum, o) => sum + Number(o.total), 0);

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(ORDERS_KEY)} />

      <FlatList
        data={past}
        keyExtractor={(o) => o.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-4 px-4 pb-3 pt-2">
            <Title>Orders</Title>

            {orders.length > 0 ? (
              <Card className="gap-1">
                <Label>Spent on collected orders</Label>
                <Money value={spent.toFixed(2)} className="text-title font-semibold text-ink" />
              </Card>
            ) : null}

            {active.length > 0 ? (
              <View className="gap-3">
                <Label>In progress</Label>
                {active.map((order) => (
                  <OrderCard key={order.id} order={order} />
                ))}
              </View>
            ) : null}

            {past.length > 0 ? <Label>Earlier</Label> : null}
          </View>
        }
        ListEmptyComponent={
          active.length > 0 ? (
            <View className="px-4">
              <Body muted>Nothing earlier yet.</Body>
            </View>
          ) : (
            <ListState
              loading={isLoading}
              error={isError ? 'Could not load your orders.' : null}
              empty="You have not ordered anything yet."
              onRetry={refetch}
            />
          )
        }
        renderItem={({ item }) => <OrderCard order={item} className="mx-4 mb-3" />}
      />
    </Screen>
  );
}
