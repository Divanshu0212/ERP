import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { Stack, router } from 'expo-router';
import { useEffect } from 'react';

import '../global.css';

import { setOnAuthFailure } from '@/lib/api/client';
import { setCacheCleaner, useSession } from '@/lib/auth/session';
import { startConnectivityWatch } from '@/lib/net/connectivity';
import { clearPersistedCache, persister, queryClient } from '@/lib/query/persister';

export default function RootLayout() {
  useEffect(() => {
    setCacheCleaner(() => {
      void clearPersistedCache();
    });

    // A refresh that cannot be recovered (revoked device, reused token)
    // must land the user on the login screen rather than an empty shell,
    // and must not leave the previous user's data cached on the device.
    setOnAuthFailure(() => {
      useSession.setState({ status: 'signed-out', user: null });
      void clearPersistedCache();
      router.replace('/(auth)/login');
    });

    const stopConnectivityWatch = startConnectivityWatch();

    // A push that only opens the app wastes the tap. The consumer puts the
    // destination in the payload, so a "payment received" push lands on the
    // fees screen rather than the home screen.
    //
    // Imported lazily for the same reason as in lib/push/register.ts: loading
    // expo-notifications runs a token auto-registration side effect, and it
    // warns loudly under Expo Go where remote push does not work at all.
    let removePushListener: (() => void) | null = null;
    void import('expo-notifications').then((Notifications) => {
      const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
        const path = response.notification.request.content.data?.path;
        if (typeof path === 'string' && path.startsWith('/')) {
          router.push(path as Parameters<typeof router.push>[0]);
        }
      });
      removePushListener = () => subscription.remove();
    });

    return () => {
      stopConnectivityWatch();
      removePushListener?.();
    };
  }, []);

  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={{ persister }}>
      <Stack screenOptions={{ headerShown: false }} />
    </PersistQueryClientProvider>
  );
}
