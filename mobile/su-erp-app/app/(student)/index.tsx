import { View } from 'react-native';

import { Body, Card, Label, Screen, Title } from '@/components/ui';
import { useSession } from '@/lib/auth/session';

export default function Home() {
  const user = useSession((s) => s.user);

  return (
    <Screen>
      <View className="gap-4 p-4">
        <Title>Student</Title>
        <Card className="gap-1">
          <Label>Signed in as</Label>
          <Body>{user?.email}</Body>
          <Body muted>{user?.user_code}</Body>
        </Card>
      </View>
    </Screen>
  );
}
