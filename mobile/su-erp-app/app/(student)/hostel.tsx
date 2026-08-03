import type { Room, RoomRequest } from '@api-types/index';
import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import {
  ALLOCATIONS_KEY,
  useAvailableRooms,
  useMyAllocation,
  useMyRoomRequests,
  useRequestRoom,
} from '@/features/hostel/useHostel';
import { cacheAge } from '@/lib/query/persister';

const REQUEST_STATUS_COPY: Record<RoomRequest['status'], string> = {
  pending: 'Waiting on the warden',
  approved: 'Approved',
  rejected: 'Rejected',
};

function RoomOption({
  room,
  selected,
  onSelect,
}: {
  room: Room;
  selected: boolean;
  onSelect: () => void;
}) {
  const free = room.capacity - room.occupied_count;

  return (
    <Press
      onPress={onSelect}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={`Room ${room.room_no}, ${room.block_name}, ${free} of ${room.capacity} beds free`}
      style={{ minHeight: 48 }}
    >
      <View
        className={`min-h-touch justify-center rounded-control border px-4 py-3 ${
          selected ? 'border-brand bg-brand-wash' : 'border-surface-border bg-surface'
        }`}
      >
        <Text className="text-body text-ink">
          {room.block_name} · Room {room.room_no}
        </Text>
        <Text className="text-detail text-ink-muted">
          {free} of {room.capacity} beds free
        </Text>
      </View>
    </Press>
  );
}

export default function HostelScreen() {
  const allocation = useMyAllocation();
  const requests = useMyRoomRequests();
  const requestRoom = useRequestRoom();
  const snack = useSnackbar();
  const [selectedRoom, setSelectedRoom] = useState<string | null>(null);

  const rows = requests.data?.results ?? [];
  const pending = rows.some((r) => r.status === 'pending');
  const canRequest = !allocation.current && !pending;

  // Only fetched when the student can actually act on it.
  const rooms = useAvailableRooms(canRequest);

  function submit() {
    if (!selectedRoom) return;

    requestRoom.mutate(
      { room_id: selectedRoom },
      {
        onSuccess: () => {
          setSelectedRoom(null);
          snack.show('Request sent to the warden.');
        },
        onError: (e) => snack.show((e as Error).message, 'critical'),
      },
    );
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(ALLOCATIONS_KEY)} />

      <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
        <View className="px-4 pb-3 pt-2">
          <Title>Hostel</Title>
        </View>

        <View className="px-4 pb-4">
          <Card className="gap-1">
            <Label>My room</Label>
            {allocation.isLoading ? (
              <Body muted>Loading</Body>
            ) : allocation.current ? (
              <>
                <Text className="text-title font-semibold text-ink">
                  {allocation.current.room_name}
                </Text>
                <Body muted>
                  Allocated{' '}
                  {new Date(allocation.current.allocated_on).toLocaleDateString([], {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                  })}
                </Body>
              </>
            ) : (
              <Body muted>No room allocated yet.</Body>
            )}
          </Card>
        </View>

        <View className="gap-3 px-4">
          <Label>Room requests</Label>

          {rows.length === 0 ? (
            <Body muted>You have not requested a room yet.</Body>
          ) : (
            rows.map((r) => (
              <Card key={r.id} className="gap-1">
                <Text className="text-body text-ink">{r.room_name}</Text>
                <Body muted>{REQUEST_STATUS_COPY[r.status]}</Body>
                {r.status === 'rejected' && r.rejection_reason ? (
                  <Text className="text-detail text-critical">{r.rejection_reason}</Text>
                ) : null}
              </Card>
            ))
          )}
        </View>

        {canRequest ? (
          <View className="gap-3 px-4 pt-6">
            <Label>Request a room</Label>

            {rooms.isLoading ? (
              <ListState loading empty="" />
            ) : (rooms.data?.results ?? []).length === 0 ? (
              <Body muted>No rooms are free right now. Check back later.</Body>
            ) : (
              <>
                {(rooms.data?.results ?? []).map((room) => (
                  <RoomOption
                    key={room.id}
                    room={room}
                    selected={selectedRoom === room.id}
                    onSelect={() => setSelectedRoom(room.id)}
                  />
                ))}

                <Button
                  label={requestRoom.isPending ? 'Sending' : 'Request this room'}
                  busy={requestRoom.isPending}
                  disabled={!selectedRoom}
                  onPress={submit}
                />
              </>
            )}
          </View>
        ) : null}
      </ScrollView>

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
