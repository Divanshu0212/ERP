import { useState } from 'react';
import { FlatList, Text, TextInput, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import {
  VISITORS_KEY,
  useCheckoutVisitor,
  useLogVisitor,
  useVisitors,
} from '@/features/warden/useWarden';
import { useConnectivity } from '@/lib/net/connectivity';
import { cacheAge } from '@/lib/query/persister';

export default function WardenVisitors() {
  const { data, isLoading, isError, refetch, isRefetching } = useVisitors();
  const log = useLogVisitor();
  const checkout = useCheckoutVisitor();
  const online = useConnectivity((s) => s.online);
  const snack = useSnackbar();

  const [name, setName] = useState('');
  const [studentCode, setStudentCode] = useState('');

  const canSubmit = name.trim().length > 0 && studentCode.trim().length > 0;

  function submit() {
    log.mutate(
      { visitor_name: name.trim(), visiting_user_code: studentCode.trim() },
      {
        onSuccess: (result) => {
          setName('');
          setStudentCode('');
          snack.show(
            result && 'queued' in result
              ? 'Saved. It will be sent when you are back online.'
              : 'Visitor logged.',
          );
        },
        onError: (e) => snack.show((e as Error).message, 'critical'),
      },
    );
  }

  function checkOut(id: string, visitorName: string) {
    checkout.mutate(id, {
      onSuccess: (result) => {
        snack.show(
          result && 'queued' in result
            ? 'Saved. It will be sent when you are back online.'
            : `${visitorName} checked out.`,
        );
      },
      onError: (e) => snack.show((e as Error).message, 'critical'),
    });
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(VISITORS_KEY)} />

      <FlatList
        data={data?.results ?? []}
        keyExtractor={(v) => v.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: 32 }}
        ListHeaderComponent={
          <View className="gap-4 px-4 pb-4 pt-2">
            <Title>Visitors</Title>

            <Card className="gap-3">
              <Label>New entry</Label>

              <TextInput
                placeholder="Visitor name"
                placeholderTextColor="#656e7a"
                value={name}
                onChangeText={setName}
                accessibilityLabel="Visitor name"
                className="min-h-touch rounded-control border border-surface-border bg-surface px-3 text-body text-ink"
              />

              <TextInput
                placeholder="Visiting (student code)"
                placeholderTextColor="#656e7a"
                autoCapitalize="characters"
                autoCorrect={false}
                value={studentCode}
                onChangeText={setStudentCode}
                accessibilityLabel="Student code being visited"
                className="min-h-touch rounded-control border border-surface-border bg-surface px-3 text-body text-ink"
              />

              {/* Said before they type: the gate is where the signal dies, and
                  a warden needs to know the entry will still be recorded. */}
              {!online ? (
                <Body muted>You are offline. This will be sent when you reconnect.</Body>
              ) : null}

              <Button
                label={log.isPending ? 'Saving' : 'Log entry'}
                busy={log.isPending}
                disabled={!canSubmit}
                onPress={submit}
              />
            </Card>

            <Label>Currently inside</Label>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load the gate register.' : null}
            empty="Nobody is signed in right now."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => (
          <Card className="mx-4 mb-3 flex-row items-center gap-3">
            <View className="flex-1 gap-1">
              <Text className="text-body font-semibold text-ink">{item.visitor_name}</Text>
              <Text className="text-detail text-ink-muted">
                Visiting {item.visiting_user_code}
              </Text>
              <Text className="text-detail text-ink-faint">
                In since{' '}
                {new Date(item.checked_in_at).toLocaleTimeString([], {
                  hour: 'numeric',
                  minute: '2-digit',
                })}
              </Text>
            </View>

            <Press
              onPress={() => checkOut(item.id, item.visitor_name)}
              accessibilityRole="button"
              accessibilityLabel={`Check out ${item.visitor_name}`}
              style={{ minHeight: 48, justifyContent: 'center' }}
            >
              <View className="min-h-touch justify-center rounded-control border border-surface-border bg-surface px-4">
                <Text className="text-body font-semibold text-brand">Check out</Text>
              </View>
            </Press>
          </Card>
        )}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
