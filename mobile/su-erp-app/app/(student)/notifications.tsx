import type { Notification } from '@api-types/index';
import { FlatList, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { ListState, Screen, Title } from '@/components/ui';
import { INBOX_KEY, useInbox, useMarkRead } from '@/features/notifications/useInbox';
import { cacheAge } from '@/lib/query/persister';

function relativeDay(iso: string): string {
  const then = new Date(iso);
  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000);

  if (days === 0) return then.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;

  return then.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

function Row({ item, onRead }: { item: Notification; onRead: (id: string) => void }) {
  return (
    <Press
      onPress={() => !item.read && onRead(item.id)}
      accessibilityRole="button"
      accessibilityLabel={`${item.read ? 'Read' : 'Unread'}: ${item.title}. ${item.body}`}
      style={{ minHeight: 48 }}
    >
      <View className="flex-row gap-3 border-b border-surface-border bg-surface px-4 py-4">
        {/* Unread is marked by a dot AND by weight — color alone disappears
            for a colorblind student and washes out in direct sunlight. */}
        <View
          className={`mt-1.5 h-2 w-2 rounded-full ${item.read ? 'bg-transparent' : 'bg-brand'}`}
        />
        <View className="flex-1 gap-1">
          <View className="flex-row items-baseline gap-3">
            <Text
              className={`flex-1 text-body text-ink ${item.read ? 'font-normal' : 'font-semibold'}`}
            >
              {item.title}
            </Text>
            <Text className="text-detail text-ink-faint">{relativeDay(item.created_at)}</Text>
          </View>
          <Text className="text-detail text-ink-muted">{item.body}</Text>
        </View>
      </View>
    </Press>
  );
}

export default function NotificationsScreen() {
  const { data, isLoading, isError, refetch, isRefetching } = useInbox();
  const markRead = useMarkRead();

  const items = data?.results ?? [];

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(INBOX_KEY)} />

      <View className="px-4 pb-3 pt-2">
        <Title>Notifications</Title>
      </View>

      <FlatList
        data={items}
        keyExtractor={(n) => n.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load your notifications.' : null}
            empty="Nothing here yet. Fee reminders and hostel notices will show up here."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => <Row item={item} onRead={markRead.mutate} />}
      />
    </Screen>
  );
}
