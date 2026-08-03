import type { BreadcrumbPoint } from '@api-types/index';
import * as Location from 'expo-location';

/** How often the driver's device samples position while a trip is running. */
export const BREADCRUMB_INTERVAL_MS = 15_000;

export async function requestPermission(): Promise<boolean> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === 'granted';
}

/**
 * Streams position while a trip is active. The timestamp comes from the
 * device, not the server, because these points are frequently delivered
 * late in a batch — see sendBreadcrumbs.
 */
export async function watchPosition(
  onPoint: (point: BreadcrumbPoint) => void,
): Promise<() => void> {
  const subscription = await Location.watchPositionAsync(
    {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: BREADCRUMB_INTERVAL_MS,
      distanceInterval: 25,
    },
    (position) => {
      onPoint({
        lat: position.coords.latitude.toFixed(6),
        lng: position.coords.longitude.toFixed(6),
        recorded_at: new Date(position.timestamp).toISOString(),
      });
    },
  );

  return () => subscription.remove();
}
