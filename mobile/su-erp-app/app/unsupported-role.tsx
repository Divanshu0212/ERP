import { Pressable, Text, View } from 'react-native';

import { useSession } from '@/lib/auth/session';

export default function UnsupportedRole() {
  const signOut = useSession((s) => s.signOut);

  return (
    <View style={{ flex: 1, justifyContent: 'center', padding: 24, gap: 16 }}>
      <Text style={{ fontSize: 20, fontWeight: '600' }}>Use the web portal</Text>
      <Text>
        Admin and superadmin tools are only available on the SU-ERP web app. Sign in there to
        manage your institution.
      </Text>
      <Pressable onPress={() => void signOut()}>
        <Text style={{ color: '#1d4ed8', fontWeight: '600' }}>Sign out</Text>
      </Pressable>
    </View>
  );
}
