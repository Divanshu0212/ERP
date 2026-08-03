import { Redirect } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { roleHome, useSession } from '@/lib/auth/session';

export default function Index() {
  const { status, user, restore } = useSession();

  useEffect(() => {
    void restore();
  }, [restore]);

  if (status === 'loading') {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }

  if (status === 'signed-out' || !user) return <Redirect href="/(auth)/login" />;

  return <Redirect href={roleHome(user.role)} />;
}
