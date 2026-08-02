import * as LocalAuthentication from 'expo-local-authentication';

/**
 * Biometric data never leaves the device and is never sent to the server —
 * this is a local gate in front of a payment, not an authentication factor
 * the backend sees. The server's protection against a bypassed client
 * remains the idempotency key on /pay.
 *
 * A device with no enrolled biometrics returns true: locking a student out of
 * paying their fees because their phone has no fingerprint reader would be
 * worse than the gate is worth.
 */
export async function authenticate(reason: string): Promise<boolean> {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  const enrolled = await LocalAuthentication.isEnrolledAsync();
  if (!hasHardware || !enrolled) return true;

  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: reason,
    disableDeviceFallback: false,
  });
  return result.success;
}
