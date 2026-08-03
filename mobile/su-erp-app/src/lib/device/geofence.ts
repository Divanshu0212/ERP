import * as Location from 'expo-location';

export interface Position {
  lat: number;
  lng: number;
  /** Android reports this directly; iOS has no equivalent and returns false. */
  mocked: boolean;
}

/**
 * A single high-accuracy fix, for marking attendance. Distinct from
 * `location.watchPosition`, which streams coarser points for a driver's
 * breadcrumb trail — here one wrong reading is the difference between being
 * marked present and being told to walk back into the room.
 */
export async function getCurrentPosition(): Promise<Position> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') throw new Error('Location permission is required.');

  const position = await Location.getCurrentPositionAsync({
    accuracy: Location.Accuracy.High,
  });

  return {
    lat: position.coords.latitude,
    lng: position.coords.longitude,
    // Reported to the server rather than silently dropped: the server
    // refuses the mark AND records the attempt, which is the useful signal.
    mocked: Boolean((position as { mocked?: boolean }).mocked),
  };
}
