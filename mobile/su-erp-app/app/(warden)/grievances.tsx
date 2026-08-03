import type { Ticket } from '@api-types/index';
import { FlatList, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, ListState, Screen, Title } from '@/components/ui';
import {
  WARDEN_TICKETS_KEY,
  useSetTicketStatus,
  useWardenTickets,
} from '@/features/warden/useWarden';
import { cacheAge } from '@/lib/query/persister';

/** Escalated first — the ML escalation exists so wardens see these on top. */
const URGENCY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

const STATUS_COPY: Record<Ticket['status'], string> = {
  open: 'Open',
  escalated: 'Escalated',
  in_progress: 'Being looked at',
  resolved: 'Resolved',
};

const STATUS_STYLE: Record<Ticket['status'], string> = {
  open: 'text-caution',
  escalated: 'text-critical',
  in_progress: 'text-brand',
  resolved: 'text-positive',
};

/**
 * Categories are free-form at the DB level, so a ticket can carry a value the
 * student surface never shows. Capitalizing alone would render "it" as "It".
 */
const CATEGORY_LABEL: Record<string, string> = {
  hostel: 'Hostel',
  academic: 'Academic',
  it: 'IT',
  ragging: 'Ragging',
  harassment: 'Harassment',
};

function categoryLabel(value: string): string {
  return CATEGORY_LABEL[value] ?? value.charAt(0).toUpperCase() + value.slice(1);
}

export default function WardenGrievances() {
  const { data, isLoading, isError, refetch, isRefetching } = useWardenTickets();
  const setStatus = useSetTicketStatus();
  const snack = useSnackbar();

  // Escalated to the top, then by urgency: the order a warden triages in.
  const tickets = [...(data?.results ?? [])].sort((a, b) => {
    const escalated = Number(b.status === 'escalated') - Number(a.status === 'escalated');
    if (escalated !== 0) return escalated;
    return (URGENCY_RANK[a.urgency ?? 'low'] ?? 9) - (URGENCY_RANK[b.urgency ?? 'low'] ?? 9);
  });

  function resolve(id: string) {
    setStatus.mutate(
      { id, status: 'resolved' },
      {
        onSuccess: (result) => {
          snack.show(
            result && 'queued' in result
              ? 'Saved. It will be sent when you are back online.'
              : 'Marked resolved.',
          );
        },
        onError: (e) => snack.show((e as Error).message, 'critical'),
      },
    );
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(WARDEN_TICKETS_KEY)} />

      <FlatList
        data={tickets}
        keyExtractor={(t) => t.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-1 px-4 pb-4 pt-2">
            <Title>Grievances</Title>
            <Body muted>Escalated complaints first.</Body>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load grievances.' : null}
            empty="No open grievances in your block."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => (
          <Card className="mx-4 mb-3 gap-2">
            <View className="flex-row items-center justify-between">
              <Text className="text-body font-semibold text-ink">
                {categoryLabel(item.category)}
              </Text>
              <Text className={`text-detail ${STATUS_STYLE[item.status]}`}>
                {STATUS_COPY[item.status]}
                {item.urgency ? ` · ${item.urgency}` : ''}
              </Text>
            </View>

            <Text className="text-detail text-ink-muted">{item.description}</Text>

            <Text className="text-detail text-ink-faint">
              Raised by {item.raised_by} ·{' '}
              {new Date(item.created_at).toLocaleDateString([], {
                day: 'numeric',
                month: 'short',
              })}
            </Text>

            {item.status !== 'resolved' ? (
              <Button
                label="Mark resolved"
                onPress={() => resolve(item.id)}
                busy={setStatus.isPending && setStatus.variables?.id === item.id}
              />
            ) : null}
          </Card>
        )}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
