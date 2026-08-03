import { useState } from 'react';
import { FlatList, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Body, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { MANIFEST_KEY, useManifest, useMySchedules } from '@/features/driver/useDriver';
import { cacheAge } from '@/lib/query/persister';

export default function DriverManifest() {
  const { data: scheduleData } = useMySchedules();
  const schedules = scheduleData?.results ?? [];

  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);
  // Default to the first schedule rather than making the driver pick one to
  // see anything at all.
  const scheduleId = selectedId ?? schedules[0]?.id;

  const { data, isLoading, isError, refetch, isRefetching } = useManifest(scheduleId);

  // A cancelled booking is not a rider; the seat is free.
  const riders = (data?.results ?? [])
    .filter((booking) => booking.status === 'booked')
    .sort((a, b) => a.seat_no - b.seat_no);

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge([...MANIFEST_KEY, scheduleId])} />

      <FlatList
        data={riders}
        keyExtractor={(b) => b.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-4 px-4 pb-4 pt-2">
            <View className="gap-1">
              <Title>Riders</Title>
              <Body muted>
                {riders.length} booked seat{riders.length === 1 ? '' : 's'}.
              </Body>
            </View>

            {schedules.length > 1 ? (
              <View className="gap-2">
                <Label>Schedule</Label>
                <View className="flex-row flex-wrap gap-2">
                  {schedules.map((schedule) => {
                    const selected = schedule.id === scheduleId;
                    return (
                      <Press
                        key={schedule.id}
                        onPress={() => setSelectedId(schedule.id)}
                        accessibilityRole="radio"
                        accessibilityState={{ selected }}
                        accessibilityLabel={`Bus ${schedule.bus_no}`}
                        style={{ minHeight: 48, justifyContent: 'center' }}
                      >
                        <View
                          className={`min-h-touch justify-center rounded-full border px-4 ${
                            selected ? 'border-brand bg-brand-wash' : 'border-surface-border bg-surface'
                          }`}
                        >
                          <Text
                            className={`text-body ${selected ? 'text-brand' : 'text-ink-muted'}`}
                          >
                            {schedule.bus_no}
                          </Text>
                        </View>
                      </Press>
                    );
                  })}
                </View>
              </View>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load the manifest.' : null}
            empty="No seats booked on this run."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => (
          <Card className="mx-4 mb-2 flex-row items-center gap-4">
            {/* Seat number leads: the driver scans down the column to find a
                seat, not down a list of names. */}
            <View className="min-w-12 items-center">
              <Text className="text-title font-semibold text-ink">{item.seat_no}</Text>
            </View>
            <Text className="flex-1 text-body text-ink">{item.student_user_code}</Text>
          </Card>
        )}
      />
    </Screen>
  );
}
