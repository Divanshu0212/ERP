import { FlatList, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { SCHEDULES_KEY, useActiveTrip, useMySchedules } from '@/features/driver/useDriver';
import { cacheAge } from '@/lib/query/persister';

function timeOf(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export default function DriverTrip() {
  const { data, isLoading, isError, refetch, isRefetching } = useMySchedules();
  const { trip, start, end } = useActiveTrip();
  const snack = useSnackbar();

  const schedules = data?.results ?? [];

  function beginTrip(scheduleId: string) {
    start.mutate(scheduleId, {
      onSuccess: () => snack.show('Trip started. Your position is being shared.'),
      onError: (e) => snack.show((e as Error).message, 'critical'),
    });
  }

  function finishTrip() {
    end.mutate(undefined, {
      onSuccess: () => snack.show('Trip ended.'),
      onError: (e) => snack.show((e as Error).message, 'critical'),
    });
  }

  // A running trip is the whole screen: at the wheel there is exactly one
  // thing to do, and the schedule list would only compete with it.
  if (trip) {
    return (
      <Screen>
        <View className="flex-1 gap-4 px-4 pt-2">
          <Title>Trip running</Title>

          <Card className="gap-2 border-positive bg-positive-wash">
            <Label>Live</Label>
            <Text className="text-body text-ink">Started {timeOf(trip.started_at)}</Text>
            <Body muted>
              Your position is shared with students on this route. Points recorded without signal
              are sent when you reconnect.
            </Body>
          </Card>

          <Button
            label={end.isPending ? 'Ending' : 'End trip'}
            tone="critical"
            busy={end.isPending}
            onPress={finishTrip}
          />
        </View>

        <Snackbar message={snack.message} onDone={snack.clear} />
      </Screen>
    );
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(SCHEDULES_KEY)} />

      <FlatList
        data={schedules}
        keyExtractor={(s) => s.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-1 px-4 pb-4 pt-2">
            <Title>Your schedules</Title>
            <Body muted>Start a trip when you pull out of the depot.</Body>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load your schedules.' : null}
            empty="You have no schedules assigned."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => (
          <Card className="mx-4 mb-3 gap-2">
            <View className="flex-row items-center justify-between">
              <Text className="text-body font-semibold text-ink">Bus {item.bus_no}</Text>
              <Text className="text-detail text-ink-faint">{timeOf(item.departure_time)}</Text>
            </View>

            <Text className="text-detail text-ink-muted">
              {item.route.name} · {item.route.start_point} to {item.route.end_point}
            </Text>

            <Button
              label={start.isPending ? 'Starting' : 'Start trip'}
              busy={start.isPending && start.variables === item.id}
              onPress={() => beginTrip(item.id)}
            />
          </Card>
        )}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
