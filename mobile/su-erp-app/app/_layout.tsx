import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack, router } from 'expo-router';
import { useEffect } from 'react';

import '../global.css';

import { setOnAuthFailure } from '@/lib/api/client';
import { useSession } from '@/lib/auth/session';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function RootLayout() {
  useEffect(() => {
    // A refresh that cannot be recovered (revoked device, reused token)
    // must land the user on the login screen rather than an empty shell.
    setOnAuthFailure(() => {
      useSession.setState({ status: 'signed-out', user: null });
      router.replace('/(auth)/login');
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <Stack screenOptions={{ headerShown: false }} />
    </QueryClientProvider>
  );
}
