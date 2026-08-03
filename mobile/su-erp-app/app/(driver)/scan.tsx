import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRef, useState } from 'react';
import { Text, View } from 'react-native';

import { Body, Button, Card, Screen, Title } from '@/components/ui';
import { submitScan } from '@/features/pass/usePass';

type Outcome = { text: string; ok: boolean };

/**
 * The driver reads this at arm's length while students board. The verdict
 * strip is deliberately the loudest thing on screen after the viewfinder —
 * a driver glancing down needs accepted-or-not in one look, not a sentence.
 */
export default function ScanScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // The camera fires continuously while a code is in frame; without this
  // guard one pass would submit dozens of scans and burn its own nonce.
  const busy = useRef(false);

  async function onScanned({ data }: { data: string }) {
    if (busy.current) return;
    busy.current = true;

    try {
      const result = await submitScan(data);
      setOutcome(
        'queued' in result
          ? { text: 'Saved offline — will sync', ok: true }
          : { text: `Accepted — ${result.student_user_code}`, ok: true },
      );
    } catch (error) {
      setOutcome({ text: (error as Error).message, ok: false });
    } finally {
      // Long enough that the driver reads the verdict before the next
      // student's code is picked up.
      setTimeout(() => {
        busy.current = false;
      }, 2000);
    }
  }

  if (!permission?.granted) {
    return (
      <Screen>
        <View className="gap-4 p-4">
          <Title>Scan passes</Title>
          <Card className="gap-4">
            <Body muted>Camera access is required to scan passes at the door.</Body>
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
          {outcome?.text ?? 'Point the camera at a student’s pass'}
        </Text>
      </View>
    </View>
  );
}
