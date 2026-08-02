import type { Ticket } from '@api-types/index';
import { useState } from 'react';
import { FlatList, Text, TextInput, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { TICKETS_KEY, useCreateTicket, useTickets } from '@/features/grievance/useGrievance';
import { useConnectivity } from '@/lib/net/connectivity';
import { cacheAge } from '@/lib/query/persister';

const CATEGORIES: { value: string; label: string }[] = [
  { value: 'hostel', label: 'Hostel' },
  { value: 'academic', label: 'Academic' },
  { value: 'it', label: 'IT' },
  { value: 'ragging', label: 'Ragging' },
  { value: 'harassment', label: 'Harassment' },
];

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

function CategoryChip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Press
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
      style={{ minHeight: 48, justifyContent: 'center' }}
    >
      <View
        className={`min-h-touch justify-center rounded-full border px-4 ${
          selected ? 'border-brand bg-brand-wash' : 'border-surface-border bg-surface'
        }`}
      >
        <Text className={`text-body ${selected ? 'text-brand' : 'text-ink-muted'}`}>{label}</Text>
      </View>
    </Press>
  );
}

export default function GrievanceScreen() {
  const { data, isLoading, isError, refetch, isRefetching } = useTickets();
  const create = useCreateTicket();
  const online = useConnectivity((s) => s.online);
  const snack = useSnackbar();

  const [category, setCategory] = useState('hostel');
  const [description, setDescription] = useState('');

  const tickets = data?.results ?? [];

  function submit() {
    create.mutate(
      { category, description: description.trim() },
      {
        onSuccess: (result) => {
          setDescription('');
          snack.show(
            result && 'queued' in result
              ? 'Saved. It will be sent when you are back online.'
              : 'Complaint filed.',
          );
        },
        onError: (e) => snack.show((e as Error).message, 'critical'),
      },
    );
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(TICKETS_KEY)} />

      <FlatList
        data={tickets}
        keyExtractor={(t) => t.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-4 px-4 pb-4 pt-2">
            <Title>Help</Title>

            <Card className="gap-3">
              <Label>What is wrong?</Label>

              <View className="flex-row flex-wrap gap-2">
                {CATEGORIES.map((option) => (
                  <CategoryChip
                    key={option.value}
                    label={option.label}
                    selected={category === option.value}
                    onPress={() => setCategory(option.value)}
                  />
                ))}
              </View>

              <TextInput
                placeholder="Describe what happened"
                placeholderTextColor="#656e7a"
                value={description}
                onChangeText={setDescription}
                multiline
                textAlignVertical="top"
                accessibilityLabel="Describe what happened"
                className="min-h-24 rounded-control border border-surface-border bg-surface p-3 text-body text-ink"
              />

              {/* Said before they type, not after they submit: a student in a
                  dead zone needs to know the complaint will still be sent. */}
              {!online ? (
                <Body muted>You are offline. This will be sent when you reconnect.</Body>
              ) : null}

              <Button
                label={create.isPending ? 'Sending' : 'File complaint'}
                busy={create.isPending}
                disabled={description.trim().length === 0}
                onPress={submit}
              />
            </Card>

            <Label>Your complaints</Label>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load your complaints.' : null}
            empty="You have not filed anything yet."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => (
          <Card className="mx-4 mb-3 gap-1">
            <View className="flex-row items-center justify-between">
              <Text className="text-body font-semibold capitalize text-ink">{item.category}</Text>
              <Text className={`text-detail ${STATUS_STYLE[item.status]}`}>
                {STATUS_COPY[item.status]}
              </Text>
            </View>
            <Text className="text-detail text-ink-muted" numberOfLines={3}>
              {item.description}
            </Text>
            <Text className="text-detail text-ink-faint">
              {new Date(item.created_at).toLocaleDateString([], {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
              })}
            </Text>
          </Card>
        )}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
