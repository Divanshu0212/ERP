import type { MenuItem } from '@api-types/index';
import { useState } from 'react';
import { FlatList, Switch, Text, TextInput, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Card, ListState, Screen, Title } from '@/components/ui';
import {
  OWNER_MENU_KEY,
  useOwnerMenu,
  useSetAvailability,
  useSetPrice,
} from '@/features/owner/useOwner';
import { cacheAge } from '@/lib/query/persister';

/**
 * One row per dish. Price commits on blur rather than per keystroke — a PATCH
 * on every digit would fire "5", "50", "500" at the server on the way to
 * "500", and the intermediate values are real prices a student could be
 * charged.
 */
function MenuRow({
  item,
  onPrice,
  onAvailability,
  busy,
}: {
  item: MenuItem;
  onPrice: (price: string) => void;
  onAvailability: (available: boolean) => void;
  busy: boolean;
}) {
  const [price, setPrice] = useState(item.price);

  function commit() {
    const trimmed = price.trim();
    // Unchanged, or not a price at all: put the server's value back rather
    // than sending something the kitchen did not mean.
    if (trimmed === item.price) return;
    if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) {
      setPrice(item.price);
      return;
    }
    onPrice(trimmed);
  }

  return (
    <Card className="mx-4 mb-3 gap-3">
      <View className="flex-row items-center gap-3">
        <Text className="flex-1 text-body font-semibold text-ink">{item.name}</Text>
        <Switch
          value={item.available}
          onValueChange={onAvailability}
          disabled={busy}
          accessibilityLabel={`${item.name} available`}
          trackColor={{ true: '#2c3ea8', false: '#e2e6ec' }}
        />
      </View>

      <View className="flex-row items-center gap-2">
        <Text className="text-body text-ink-muted">₹</Text>
        <TextInput
          value={price}
          onChangeText={setPrice}
          onBlur={commit}
          keyboardType="decimal-pad"
          returnKeyType="done"
          accessibilityLabel={`${item.name} price`}
          className="min-h-touch flex-1 rounded-control border border-surface-border bg-surface px-3 text-body text-ink"
        />
      </View>

      {!item.available ? <Body muted>Hidden from students right now.</Body> : null}
    </Card>
  );
}

export default function OwnerMenu() {
  const { data, isLoading, isError, refetch, isRefetching } = useOwnerMenu();
  const setPrice = useSetPrice();
  const setAvailability = useSetAvailability();
  const snack = useSnackbar();

  const items = data?.results ?? [];

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(OWNER_MENU_KEY)} />

      <FlatList
        data={items}
        keyExtractor={(item) => item.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-1 px-4 pb-4 pt-2">
            <Title>Menu</Title>
            <Body muted>Turn a dish off the moment it runs out.</Body>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load the menu.' : null}
            empty="No dishes on the menu yet."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => (
          <MenuRow
            item={item}
            busy={setAvailability.isPending && setAvailability.variables?.id === item.id}
            onPrice={(price) =>
              setPrice.mutate(
                { id: item.id, price },
                {
                  onSuccess: () => snack.show(`${item.name} price updated.`),
                  onError: (e) => snack.show((e as Error).message, 'critical'),
                },
              )
            }
            onAvailability={(available) =>
              setAvailability.mutate(
                { id: item.id, available },
                {
                  onSuccess: () =>
                    snack.show(available ? `${item.name} is back on.` : `${item.name} turned off.`),
                  onError: (e) => snack.show((e as Error).message, 'critical'),
                },
              )
            }
          />
        )}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
