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

    return startConnectivityWatch();
  }, []);

  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={{ persister }}>
      <Stack screenOptions={{ headerShown: false }} />
    </PersistQueryClientProvider>
  );
}
