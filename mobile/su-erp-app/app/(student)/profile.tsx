import type { DeviceSummary } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { Alert, ScrollView, Text, View } from 'react-native';

import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { listDevices, revokeDevice } from '@/lib/api/auth';
import { getDeviceId } from '@/lib/device/identity';
import { useSession } from '@/lib/auth/session';

const DEVICES_KEY = ['auth', 'devices'];

function lastSeen(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);

  if (minutes < 2) return 'Active now';
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} hr ago`;

  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' });
}

function DeviceRow({
  device,
  isThisDevice,
  onRevoke,
  busy,
}: {
  device: DeviceSummary;
  isThisDevice: boolean;
  onRevoke: () => void;
  busy: boolean;
}) {
  return (
    <View className="flex-row items-center gap-3 border-b border-surface-border py-3">
      <View className="flex-1 gap-0.5">
        <Text className="text-body text-ink">
          {device.model_name || device.platform}
          {isThisDevice ? ' · This device' : ''}
        </Text>
        <Text className="text-detail text-ink-faint">{lastSeen(device.last_seen_at)}</Text>
      </View>

      {!isThisDevice ? (
        <Button label={busy ? 'Removing' : 'Sign out'} tone="quiet" busy={busy} onPress={onRevoke} />
      ) : null}
    </View>
  );
}

export default function ProfileScreen() {
  const user = useSession((s) => s.user);
  const signOut = useSession((s) => s.signOut);
  const client = useQueryClient();
  const snack = useSnackbar();

  const devices = useQuery({ queryKey: DEVICES_KEY, queryFn: listDevices });
  const thisDeviceId = useQuery({ queryKey: ['device', 'id'], queryFn: getDeviceId });

  const revoke = useMutation({
    mutationFn: revokeDevice,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: DEVICES_KEY });
      snack.show('That device has been signed out.');
    },
    onError: (e) => snack.show((e as Error).message, 'critical'),
  });

  /**
   * Confirmed, unlike the transient outcomes elsewhere in the app: revoking a
   * session cannot be undone from here, and the student may be looking at a
   * list where two phones share a model name.
   */
  function confirmRevoke(device: DeviceSummary) {
    Alert.alert(
      'Sign out this device?',
      `${device.model_name || device.platform} will have to sign in again.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign out',
          style: 'destructive',
          onPress: () => revoke.mutate(device.device_id),
        },
      ],
    );
  }

  function confirmSignOut() {
    Alert.alert('Sign out?', 'You will need your password to sign back in.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign out',
        style: 'destructive',
        onPress: async () => {
          await signOut();
          router.replace('/(auth)/login');
        },
      },
    ]);
  }

  const rows = devices.data ?? [];

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
        <View className="gap-1 px-4 pb-4 pt-2">
          <Title>Profile</Title>
          <Body>{user?.email}</Body>
          <Body muted>{user?.user_code}</Body>
        </View>

        <View className="px-4">
          <Card className="gap-1">
            <Label>Signed-in devices</Label>

            {devices.isLoading || rows.length === 0 ? (
              <ListState
                loading={devices.isLoading}
                error={devices.isError ? 'Could not load your devices.' : null}
                empty="No other devices."
                onRetry={devices.refetch}
              />
            ) : (
              rows.map((device) => (
                <DeviceRow
                  key={device.device_id}
                  device={device}
                  isThisDevice={device.device_id === thisDeviceId.data}
                  busy={revoke.isPending && revoke.variables === device.device_id}
                  onRevoke={() => confirmRevoke(device)}
                />
              ))
            )}
          </Card>
        </View>

        <View className="px-4 pt-6">
          <Button label="Sign out" tone="critical" onPress={confirmSignOut} />
        </View>
      </ScrollView>

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
