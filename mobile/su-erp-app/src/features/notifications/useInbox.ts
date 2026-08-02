import type { Notification, Paginated } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { unreadCount } from '@/features/home/summary';
import { fetchInbox, markRead } from '@/lib/api/notify';

export const INBOX_KEY = ['notify', 'inbox'];

export function useInbox() {
  return useQuery({ queryKey: INBOX_KEY, queryFn: () => fetchInbox() });
}

/**
 * The optimistic edit, kept pure so it can be tested without a renderer.
 * Returns a new page with one row flipped to read.
 */
export function applyRead(
  page: Paginated<Notification> | undefined,
  id: string,
): Paginated<Notification> | undefined {
  if (!page) return page;

  return {
    ...page,
    results: page.results.map((n) => (n.id === id ? { ...n, read: true } : n)),
  };
}

export function useMarkRead() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: markRead,

    /**
     * Applied optimistically: tapping a notification is a read receipt, not a
     * decision, and waiting on a round trip to dim the row makes the list feel
     * broken on a slow campus connection. Rolled back if the request fails.
     */
    onMutate: async (id: string) => {
      await client.cancelQueries({ queryKey: INBOX_KEY });
      const previous = client.getQueryData<Paginated<Notification>>(INBOX_KEY);

      client.setQueryData<Paginated<Notification>>(INBOX_KEY, (current) =>
        applyRead(current, id),
      );

      return { previous };
    },

    onError: (_error, _id, context) => {
      if (context?.previous) client.setQueryData(INBOX_KEY, context.previous);
    },

    onSettled: () => client.invalidateQueries({ queryKey: INBOX_KEY }),
  });
}

/** Unread count, for the home dashboard and the tab badge. */
export function useUnreadCount(): number {
  const { data } = useInbox();
  return unreadCount(data?.results ?? []);
}
