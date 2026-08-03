import type { Allocation } from '@api-types/index';
import { useMemo } from 'react';
import { SectionList, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Body, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { ROSTER_KEY, useBlockRoster } from '@/features/warden/useWarden';
import { cacheAge } from '@/lib/query/persister';

type RoomSection = { title: string; data: Allocation[] };

/**
 * Grouped by room rather than listed flat: a warden walking the block reads
 * door by door, so the room number is the heading and the residents sit under
 * it. A flat list of names forces them to reconstruct that grouping in
 * their head at every door.
 */
function groupByRoom(allocations: Allocation[]): RoomSection[] {
  const rooms = new Map<string, Allocation[]>();

  for (const allocation of allocations) {
    const existing = rooms.get(allocation.room_name);
    if (existing) existing.push(allocation);
    else rooms.set(allocation.room_name, [allocation]);
  }

  return [...rooms.entries()]
    .map(([title, data]) => ({ title, data }))
    .sort((a, b) => a.title.localeCompare(b.title, undefined, { numeric: true }));
}

export default function WardenBlock() {
  const { data, isLoading, isError, refetch, isRefetching } = useBlockRoster();

  const allocations = data?.results ?? [];
  const sections = useMemo(() => groupByRoom(allocations), [allocations]);

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(ROSTER_KEY)} />

      <SectionList
        sections={sections}
        keyExtractor={(item) => item.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-1 px-4 pb-4 pt-2">
            <Title>Block roster</Title>
            <Body muted>
              {allocations.length} resident{allocations.length === 1 ? '' : 's'} across{' '}
              {sections.length} room{sections.length === 1 ? '' : 's'}.
            </Body>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load the roster.' : null}
            empty="No confirmed allocations yet."
            onRetry={refetch}
          />
        }
        renderSectionHeader={({ section }) => (
          <View className="px-4 pb-2 pt-4">
            <Label>{section.title}</Label>
          </View>
        )}
        renderItem={({ item }) => (
          <Card className="mx-4 mb-2 gap-1">
            <Text className="text-body font-semibold text-ink">{item.student_user_code}</Text>
            <Text className="text-detail text-ink-faint">
              Since{' '}
              {new Date(item.allocated_on).toLocaleDateString([], {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
              })}
            </Text>
          </Card>
        )}
      />
    </Screen>
  );
}
