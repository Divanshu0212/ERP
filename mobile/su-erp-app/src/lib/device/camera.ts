import * as ImagePicker from 'expo-image-picker';

/** Keeps uploads small enough to survive a campus connection. */
const QUALITY = 0.6;

export async function capturePhoto(): Promise<{ uri: string } | null> {
  const permission = await ImagePicker.requestCameraPermissionsAsync();
  if (!permission.granted) throw new Error('Camera access is required to attach a photo.');

  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ['images'],
    quality: QUALITY,
    // Stripped deliberately: a photo of a hostel room carries GPS coordinates
    // and a capture timestamp, and the ticket already records who filed it
    // and when. The extra metadata only widens what a leak would expose.
    exif: false,
  });

  if (result.canceled) return null;
  return { uri: result.assets[0].uri };
}
