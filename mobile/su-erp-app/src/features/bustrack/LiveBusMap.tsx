import { View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';

import { Body, Card, Label } from '@/components/ui';

import { useLiveBus } from './useLiveBus';

/** Roughly a campus-sized view around the bus. */
const SPAN_DEGREES = 0.01;

/**
 * Where the bus is right now on the selected route.
 *
 * Renders a sentence rather than an empty grey rectangle when no bus is
 * running: a map with nothing on it reads as "broken", while "no bus running"
 * answers the question the student actually opened the screen to ask.
 */
export function LiveBusMap({ routeId }: { routeId: string | null }) {
  const live = useLiveBus(routeId);

  if (live.isLoading) {
    return (
      <Card>
        <Body muted>Looking for the bus…</Body>
      </Card>
    );
  }

  if (live.isError || !live.data) {
    return (
      <Card>
        <Body muted>No bus running on this route right now.</Body>
      </Card>
    );
  }

  const lat = Number(live.data.lat);
  const lng = Number(live.data.lng);

  return (
    <View className="gap-2">
      <View className="h-56 overflow-hidden rounded-card border border-surface-border">
        <MapView
          style={{ flex: 1 }}
          // Re-centres as the bus moves rather than fighting the student's
          // pan: the marker is the only thing worth looking at here.
          region={{
            latitude: lat,
            longitude: lng,
            latitudeDelta: SPAN_DEGREES,
            longitudeDelta: SPAN_DEGREES,
          }}
          pointerEvents="none"
        >
          <Marker coordinate={{ latitude: lat, longitude: lng }} title="Bus" />
        </MapView>
      </View>
      <Label>Updated {new Date(live.data.recorded_at).toLocaleTimeString([], {
        hour: 'numeric',
        minute: '2-digit',
      })}</Label>
    </View>
  );
}
