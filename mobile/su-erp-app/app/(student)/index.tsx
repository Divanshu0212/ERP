import { Text, View } from 'react-native';

import { useSession } from '@/lib/auth/session';

export default function Home() {
  const user = useSession((s) => s.user);

  return (
    <View style={{ flex: 1, padding: 24, gap: 8 }}>
      <Text style={{ fontSize: 22, fontWeight: '600' }}>Student</Text>
      <Text>{user?.email}</Text>
      <Text>{user?.user_code}</Text>
    </View>
  );
}
