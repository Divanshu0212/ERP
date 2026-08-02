import type { MenuItem, Order } from '@api-types/index';
import { FlatList, Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { useCart } from '@/features/canteen/useCart';
import { MENU_KEY, useMenu } from '@/features/canteen/useMenu';
import { isActive, useOrders, usePlaceOrder } from '@/features/canteen/useOrders';
import { cacheAge } from '@/lib/query/persister';

/** Kitchen states in the order they happen, so the student can see progress. */
const STAGES: Order['status'][] = ['placed', 'preparing', 'ready'];

const STAGE_COPY: Record<string, string> = {
  placed: 'Order placed',
  preparing: 'Being prepared',
  ready: 'Ready for pickup',
};

function ActiveOrder({ order }: { order: Order }) {
  const reached = STAGES.indexOf(order.status);

  return (
    <Card className="mx-4 mb-3 gap-3 border-brand/30 bg-brand-wash">
      <View className="flex-row items-center justify-between">
        <Label>{STAGE_COPY[order.status] ?? order.status}</Label>
        <Money value={order.total} className="text-body font-semibold text-ink" />
      </View>

      {/* Three segments beat a spinner: the student can see how far along the
          kitchen is and roughly when to walk over. */}
      <View className="flex-row gap-1.5">
        {STAGES.map((stage, index) => (
          <View
            key={stage}
            className={`h-1 flex-1 rounded-full ${index <= reached ? 'bg-brand' : 'bg-surface-border'}`}
          />
        ))}
      </View>

      <Text className="text-detail text-ink-muted">
        {order.items.map((i) => `${i.quantity}x ${i.name}`).join(', ')}
      </Text>
    </Card>
  );
}

function MenuRow({ item }: { item: MenuItem }) {
  const quantity = useCart((s) => s.lines[item.id] ?? 0);
  const add = useCart((s) => s.add);
  const remove = useCart((s) => s.remove);

  return (
    <View className="mx-4 mb-3 flex-row items-center gap-3 rounded-card border border-surface-border bg-surface p-4">
      <View className="flex-1 gap-1">
        <Text className={`text-body ${item.available ? 'text-ink' : 'text-ink-faint'}`}>
          {item.name}
        </Text>
        <Money
          value={item.price}
          className={`text-detail ${item.available ? 'text-ink-muted' : 'text-ink-faint'}`}
        />
      </View>

      {!item.available ? (
        <Text className="text-detail text-ink-faint">Sold out</Text>
      ) : quantity === 0 ? (
        <Press
          onPress={() => add(item.id)}
          accessibilityRole="button"
          accessibilityLabel={`Add ${item.name}`}
          style={{ minHeight: 48, justifyContent: 'center' }}
        >
          <View className="min-h-touch justify-center rounded-control border border-surface-border px-4">
            <Text className="text-body font-semibold text-brand">Add</Text>
          </View>
        </Press>
      ) : (
        <View className="flex-row items-center gap-1">
          <Press
            onPress={() => remove(item.id)}
            accessibilityRole="button"
            accessibilityLabel={`Remove one ${item.name}`}
            style={{ minHeight: 48, minWidth: 48, justifyContent: 'center' }}
          >
            <View className="min-h-touch min-w-touch items-center justify-center">
              <Text className="text-title text-brand">−</Text>
            </View>
          </Press>

          <Text
            className="min-w-6 text-center text-body font-semibold text-ink"
            accessibilityLabel={`${quantity} in cart`}
          >
            {quantity}
          </Text>

          <Press
            onPress={() => add(item.id)}
            accessibilityRole="button"
            accessibilityLabel={`Add one more ${item.name}`}
            style={{ minHeight: 48, minWidth: 48, justifyContent: 'center' }}
          >
            <View className="min-h-touch min-w-touch items-center justify-center">
              <Text className="text-title text-brand">+</Text>
            </View>
          </Press>
        </View>
      )}
    </View>
  );
}

export default function CanteenScreen() {
  const { data: menu, isLoading, isError, refetch, isRefetching } = useMenu();
  const { data: orders } = useOrders();
  const lines = useCart((s) => s.lines);
  const toLines = useCart((s) => s.toLines);
  const count = useCart((s) => s.count);
  const place = usePlaceOrder();
  const snack = useSnackbar();

  const items = menu?.results ?? [];
  const active = (orders?.results ?? []).filter(isActive);

  // Priced from the menu the student is looking at, so the cart bar can show a
  // total before they commit rather than after the server replies.
  const total = items.reduce((sum, item) => sum + Number(item.price) * (lines[item.id] ?? 0), 0);

  function checkout() {
    place.mutate(toLines(), {
      onSuccess: () => snack.show('Order placed.'),
      onError: (e) => snack.show((e as Error).message, 'critical'),
    });
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(MENU_KEY)} />

      <FlatList
        data={items}
        keyExtractor={(m) => m.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        contentContainerStyle={{ paddingBottom: count() > 0 ? 96 : 8 }}
        ListHeaderComponent={
          <View className="gap-3 pb-1 pt-2">
            <View className="px-4">
              <Title>Canteen</Title>
            </View>
            {active.map((order) => (
              <ActiveOrder key={order.id} order={order} />
            ))}
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load the menu.' : null}
            empty="The menu is empty right now."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => <MenuRow item={item} />}
      />

      {count() > 0 ? (
        <View className="absolute inset-x-0 bottom-0 border-t border-surface-border bg-surface px-4 pb-6 pt-3">
          <View className="mb-2 flex-row items-center justify-between">
            <Body muted>
              {count()} {count() === 1 ? 'item' : 'items'}
            </Body>
            <Money value={total.toFixed(2)} className="text-heading font-semibold text-ink" />
          </View>
          <Button
            label={place.isPending ? 'Placing order' : 'Place order'}
            busy={place.isPending}
            onPress={checkout}
          />
        </View>
      ) : null}

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
