import { View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { Body, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { usePassToken } from '@/features/pass/usePass';

/**
 * The QR is the whole screen. A student holds this up in a queue at a bus
 * door, often one-handed and in daylight — a large, high-contrast code with
 * nothing competing for attention is the entire job of this screen.
 */
export default function PassScreen() {
  const { data, isLoading, isError, refetch } = usePassToken();

  return (
    <Screen>
      <View className="gap-4 p-4">
        <Title>Bus pass</Title>

        {isLoading || isError || !data ? (
          <ListState
            loading={isLoading}
            error={
              isError
                ? 'You have no active bus pass. Book a seat and complete payment to activate one.'
                : null
            }
            empty="No active bus pass."
            onRetry={() => void refetch()}
          />
        ) : (
          <Card className="items-center gap-4 py-8">
            {/* White quiet zone under the code: scanners on cheap driver
                phones fail against a tinted background. */}
            <View className="rounded-card bg-surface p-4">
              <QRCode value={data.token} size={260} backgroundColor="#ffffff" color="#16181d" />
            </View>
            <View className="items-center gap-1">
              <Label>Show this at the door</Label>
              <Body muted>Refreshes every {data.expires_in} seconds</Body>
            </View>
          </Card>
        )}
      </View>
    </Screen>
  );
}
