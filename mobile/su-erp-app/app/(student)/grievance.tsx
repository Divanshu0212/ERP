import type { Ticket } from '@api-types/index';
import { useState } from 'react';
import { FlatList, Image, Text, TextInput, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { TICKETS_KEY, useCreateTicket, useTickets } from '@/features/grievance/useGrievance';
import { capturePhoto } from '@/lib/device/camera';
import { useConnectivity } from '@/lib/net/connectivity';
import { enqueueMedia, replayMedia } from '@/lib/offline/mediaQueue';
import { cacheAge } from '@/lib/query/persister';

const CATEGORIES: { value: string; label: string }[] = [
  { value: 'hostel', label: 'Hostel' },
  { value: 'academic', label: 'Academic' },
  { value: 'it', label: 'IT' },
  { value: 'ragging', label: 'Ragging' },
  { value: 'harassment', label: 'Harassment' },
];

/**
 * Categories are free-form at the DB level, so a ticket can carry a value with
 * no chip. Falling back to capitalize() alone would render "it" as "It".
 */
function categoryLabel(value: string): string {
  const known = CATEGORIES.find((c) => c.value === value);
  return known ? known.label : value.charAt(0).toUpperCase() + value.slice(1);
}

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
  const [photoUri, setPhotoUri] = useState<string | null>(null);

  const tickets = data?.results ?? [];

  async function attachPhoto() {
    try {
      const photo = await capturePhoto();
      if (photo) setPhotoUri(photo.uri);
    } catch (e) {
      snack.show((e as Error).message, 'critical');
    }
  }

  function submit() {
    create.mutate(
      { category, description: description.trim() },
      {
        onSuccess: (result) => {
          const queued = Boolean(result && 'queued' in result);

          // A photo can only be attached to a ticket that actually exists.
          // When the ticket itself queued, there is no id yet, so the photo
          // waits with it rather than uploading to nothing.
          if (photoUri && !queued && result) {
            void enqueueMedia((result as Ticket).id, photoUri).then(() => replayMedia());
          }

          setDescription('');
          if (!queued) setPhotoUri(null);
          snack.show(
            queued
              ? photoUri
                ? 'Saved. Your complaint and photo will be sent when you are back online.'
                : 'Saved. It will be sent when you are back online.'
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

              <View className="flex-row items-center gap-3">
                <View className="flex-1">
                  <Button
                    label={photoUri ? 'Retake photo' : 'Attach photo'}
                    tone="quiet"
                    onPress={() => void attachPhoto()}
                  />
                </View>
                {photoUri ? (
                  <Image
                    source={{ uri: photoUri }}
                    className="h-12 w-12 rounded-control"
                    accessibilityLabel="Attached photo"
                  />
                ) : null}
              </View>

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
              <Text className="text-body font-semibold text-ink">
                {categoryLabel(item.category)}
              </Text>
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
            {/* Says the photo existed and is gone, rather than rendering a
                broken thumbnail once the retention sweep has run. */}
            {item.media_count > 0 ? (
              <Text className="text-detail text-ink-faint">
                {item.media_count} {item.media_count === 1 ? 'attachment' : 'attachments'}
                {item.media_purged_at
                  ? `, purged ${new Date(item.media_purged_at).toLocaleDateString([], {
                      day: 'numeric',
                      month: 'short',
                    })}`
                  : ''}
              </Text>
            ) : null}
          </Card>
        )}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
