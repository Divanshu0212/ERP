import type { Route, ScheduleSeats } from '@api-types/index';
import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { LiveBusMap } from '@/features/bustrack/LiveBusMap';
import { ROUTES_KEY, useBookSeat, useRoutes, useSeats } from '@/features/transport/useTransport';
import { cacheAge } from '@/lib/query/persister';

function departureLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function RouteOption({
  route,
  selected,
  onSelect,
}: {
  route: Route;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <Press
      onPress={onSelect}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={`${route.name}, ${route.start_point} to ${route.end_point}`}
      style={{ minHeight: 48 }}
    >
      <View
        className={`min-h-touch justify-center rounded-control border px-4 py-3 ${
          selected ? 'border-brand bg-brand-wash' : 'border-surface-border bg-surface'
        }`}
      >
        <Text className="text-body text-ink">{route.name}</Text>
        <Text className="text-detail text-ink-muted">
          {route.start_point} to {route.end_point}
        </Text>
      </View>
    </Press>
  );
}

function ScheduleOption({
  schedule,
  selected,
  onSelect,
}: {
  schedule: ScheduleSeats;
  selected: boolean;
  onSelect: () => void;
}) {
  const full = schedule.available === 0;

  return (
    <Press
      onPress={onSelect}
      disabled={full}
      accessibilityRole="radio"
      accessibilityState={{ selected, disabled: full }}
      accessibilityLabel={`Bus ${schedule.bus_no}, departs ${departureLabel(schedule.departure_time)}, ${
        full ? 'full' : `${schedule.available} seats free`
      }`}
      style={{ minHeight: 48 }}
    >
      <View
        className={`min-h-touch flex-row items-center justify-between rounded-control border px-4 py-3 ${
          selected ? 'border-brand bg-brand-wash' : 'border-surface-border bg-surface'
        }`}
      >
        <View>
          <Text className={`text-body ${full ? 'text-ink-faint' : 'text-ink'}`}>
            {departureLabel(schedule.departure_time)}
          </Text>
          <Text className="text-detail text-ink-muted">Bus {schedule.bus_no}</Text>
        </View>
        <Text className={`text-detail ${full ? 'text-ink-faint' : 'text-positive'}`}>
          {full ? 'Full' : `${schedule.available} free`}
        </Text>
      </View>
    </Press>
  );
}

function SeatGrid({
  schedule,
  onBook,
  busy,
}: {
  schedule: ScheduleSeats;
  onBook: (seat: number) => void;
  busy: boolean;
}) {
  const taken = new Set(schedule.taken);

  return (
    <View className="flex-row flex-wrap gap-2">
      {/* Seats come from the bus's own capacity — a fixed 40 would invent seats
          on a minibus and hide them on a coach. */}
      {Array.from({ length: schedule.capacity }, (_, i) => i + 1).map((seat) => {
        const gone = taken.has(seat);

        return (
          <Press
            key={seat}
            disabled={gone || busy}
            onPress={() => onBook(seat)}
            accessibilityRole="button"
            accessibilityState={{ disabled: gone }}
            accessibilityLabel={`Seat ${seat}${gone ? ', already booked' : ''}`}
            style={{ minHeight: 48, minWidth: 48 }}
          >
            <View
              className={`min-h-touch min-w-touch items-center justify-center rounded-control border ${
                gone ? 'border-surface-border bg-surface-sunken' : 'border-brand bg-brand-wash'
              }`}
            >
              <Text className={`text-body ${gone ? 'text-ink-faint' : 'text-brand'}`}>{seat}</Text>
            </View>
          </Press>
        );
      })}
    </View>
  );
}

export default function TransportScreen() {
  const [routeId, setRouteId] = useState<string | null>(null);
  const [scheduleId, setScheduleId] = useState<string | null>(null);
  const routes = useRoutes();
  const seats = useSeats(routeId);
  const book = useBookSeat(scheduleId, routeId);
  const snack = useSnackbar();

  const schedules = seats.data ?? [];
  const selected = schedules.find((s) => s.schedule_id === scheduleId);

  function onBook(seat: number) {
    book.mutate(seat, {
      onSuccess: () => snack.show(`Seat ${seat} booked.`),
      onError: (e) => snack.show((e as Error).message, 'critical'),
    });
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(ROUTES_KEY)} />

      <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
        <View className="px-4 pb-3 pt-2">
          <Title>Bus</Title>
        </View>

        <View className="gap-3 px-4">
          <Label>Route</Label>
          {routes.isLoading || (routes.data?.results ?? []).length === 0 ? (
            <ListState
              loading={routes.isLoading}
              error={routes.isError ? 'Could not load routes.' : null}
              empty="No routes are running."
              onRetry={routes.refetch}
            />
          ) : (
            (routes.data?.results ?? []).map((route) => (
              <RouteOption
                key={route.id}
                route={route}
                selected={routeId === route.id}
                onSelect={() => {
                  setRouteId(route.id);
                  setScheduleId(null);
                }}
              />
            ))
          )}
        </View>

        {routeId ? (
          <View className="gap-3 px-4 pt-6">
            <Label>Where the bus is</Label>
            <LiveBusMap routeId={routeId} />
          </View>
        ) : null}

        {routeId ? (
          <View className="gap-3 px-4 pt-6">
            <Label>Departure</Label>
            {seats.isLoading ? (
              <ListState loading empty="" />
            ) : schedules.length === 0 ? (
              <Body muted>No buses scheduled on this route.</Body>
            ) : (
              schedules.map((schedule) => (
                <ScheduleOption
                  key={schedule.schedule_id}
                  schedule={schedule}
                  selected={scheduleId === schedule.schedule_id}
                  onSelect={() => setScheduleId(schedule.schedule_id)}
                />
              ))
            )}
          </View>
        ) : null}

        {selected ? (
          <View className="gap-3 px-4 pt-6">
            <Label>Pick a seat</Label>
            <Card>
              <SeatGrid schedule={selected} onBook={onBook} busy={book.isPending} />
            </Card>
          </View>
        ) : null}
      </ScrollView>

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
