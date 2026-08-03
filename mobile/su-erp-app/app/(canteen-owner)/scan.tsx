import { useQueryClient } from '@tanstack/react-query';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRef, useState } from 'react';
import { Text, View } from 'react-native';

import { Body, Button, Card, Screen, Title } from '@/components/ui';
import { ORDERS_KEY } from '@/features/canteen/useOrders';
import { scanPickup } from '@/lib/api/owner';

type Outcome = { text: string; ok: boolean };

/**
 * Scanning a student's pickup code is the only way an order reaches
 * `completed`, so this screen is the counter's last step in the flow.
 */
export default function OwnerScanScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const client = useQueryClient();
  // The camera fires continuously while a code is in frame; without this
  // guard one order would submit dozens of identical completions.
  const busy = useRef(false);

  async function onScanned({ data }: { data: string }) {
    if (busy.current) return;
    busy.current = true;

    try {
      const order = await scanPickup(data);
      setOutcome({ text: `Handed over — ${order.student_user_code}`, ok: true });
      void client.invalidateQueries({ queryKey: ORDERS_KEY });
    } catch (error) {
      setOutcome({ text: (error as Error).message, ok: false });
    } finally {
      // Long enough to read the verdict before the next code is picked up.
      setTimeout(() => {
        busy.current = false;
      }, 2000);
    }
  }

  if (!permission?.granted) {
    return (
      <Screen>
        <View className="gap-4 p-4">
          <Title>Scan pickup</Title>
          <Card className="gap-4">
            <Body muted>Camera access is required to scan a student&rsquo;s pickup code.</Body>
            <Button label="Grant camera access" onPress={() => void requestPermission()} />
          </Card>
        </View>
      </Screen>
    );
  }

  return (
    <View className="flex-1 bg-ink">
      <CameraView
        style={{ flex: 1 }}
        barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        onBarcodeScanned={onScanned}
      />
      <View
        className={`min-h-touch justify-center px-4 py-4 ${
          outcome === null ? 'bg-ink' : outcome.ok ? 'bg-brand' : 'bg-critical'
        }`}
        accessibilityLiveRegion="polite"
      >
        <Text className="text-center text-body font-semibold text-white">
          {outcome?.text ?? 'Point the camera at the student’s code'}
        </Text>
      </View>
    </View>
  );
}
