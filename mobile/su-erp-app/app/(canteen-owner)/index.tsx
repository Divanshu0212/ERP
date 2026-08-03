import type { Order, OrderStatus } from '@api-types/index';
import { SectionList, Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { BOARD_KEY, useAdvanceOrder, useOrderBoard } from '@/features/owner/useOwner';
import { NEXT_STATUS } from '@/lib/api/owner';
import { cacheAge } from '@/lib/query/persister';

/** Completed and cancelled orders leave the board — they need no action. */
const LANES: OrderStatus[] = ['placed', 'preparing', 'ready'];

const LANE_COPY: Record<string, string> = {
  placed: 'New',
  preparing: 'Cooking',
  ready: 'Ready for pickup',
};

const NEXT_LABEL: Record<string, string> = {
  preparing: 'Start cooking',
  ready: 'Mark ready',
  completed: 'Hand over',
};

export default function OrderBoard() {
  const { data, isLoading, isError, refetch, isRefetching } = useOrderBoard();
  const advance = useAdvanceOrder();
  const snack = useSnackbar();

  const orders = data?.results ?? [];

  // Oldest first inside a lane: the queue a kitchen actually works.
  const sections = LANES.map((lane) => ({
    title: lane,
    data: orders
      .filter((order) => order.status === lane)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
  }));

  const active = sections.reduce((sum, section) => sum + section.data.length, 0);

  function advanceTo(order: Order) {
    const next = NEXT_STATUS[order.status];
    if (!next) return;

    advance.mutate(
      { id: order.id, status: next },
      {
        onSuccess: (result) => {
          snack.show(
            result && 'queued' in result
              ? 'Saved. It will be sent when you are back online.'
              : `Order moved to ${LANE_COPY[next] ?? next}.`,
          );
        },
        onError: (e) => snack.show((e as Error).message, 'critical'),
      },
    );
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(BOARD_KEY)} />

      <SectionList
        sections={sections}
        keyExtractor={(item) => item.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-1 px-4 pb-2 pt-2">
            <Title>Orders</Title>
            <Body muted>
              {active} order{active === 1 ? '' : 's'} on the board.
            </Body>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load the order board.' : null}
            empty="No orders right now."
            onRetry={refetch}
          />
        }
        renderSectionHeader={({ section }) => (
          <View className="flex-row items-baseline gap-2 px-4 pb-2 pt-4">
            <Label>{LANE_COPY[section.title] ?? section.title}</Label>
            <Text className="text-detail text-ink-faint">{section.data.length}</Text>
          </View>
        )}
        renderSectionFooter={({ section }) =>
          section.data.length === 0 ? (
            <Text className="px-4 pb-1 text-detail text-ink-faint">Nothing here.</Text>
          ) : null
        }
        renderItem={({ item }) => {
          const next = NEXT_STATUS[item.status];

          return (
            <Card className="mx-4 mb-3 gap-2">
              <View className="flex-row items-center justify-between">
                <Text className="text-body font-semibold text-ink">{item.student_user_code}</Text>
                <Money value={item.total} className="text-body font-semibold text-ink" />
              </View>

              {item.items.map((line) => (
                <Text key={line.id} className="text-detail text-ink-muted">
                  {line.quantity}× {line.name}
                </Text>
              ))}

              {next ? (
                <Button
                  label={NEXT_LABEL[next] ?? `Mark ${next}`}
                  busy={advance.isPending && advance.variables?.id === item.id}
                  onPress={() => advanceTo(item)}
                />
              ) : null}
            </Card>
          );
        }}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
