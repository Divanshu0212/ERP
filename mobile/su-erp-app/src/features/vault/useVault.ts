import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Directory, File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

import { getAccessToken, refreshSession } from '@/lib/api/client';
import { resolveBaseUrl } from '@/lib/api/endpoint';
import { receiptPdfUrl } from '@/lib/api/finance';

export const VAULT_KEY = ['vault', 'documents'];

export interface VaultEntry {
  name: string;
  uri: string;
  size: number | null;
}

/**
 * Documents live in the app's *document* directory, not the cache: the cache
 * is exactly what Android reclaims when storage runs low, and a receipt the
 * student saved for an airplane-mode trip has to still be there. See
 * features/receipts/useReceipt.ts, which deliberately uses the cache instead
 * because those files are transient.
 */
function vaultDirectory(): Directory {
  const directory = new Directory(Paths.document, 'vault');
  if (!directory.exists) directory.create({ intermediates: true });
  return directory;
}

/**
 * Reads the folder, not the API. That is the entire point of the vault: with
 * no network at all, the list still renders and the files still open.
 */
export function listVault(): VaultEntry[] {
  return vaultDirectory()
    .list()
    .filter((entry): entry is File => entry instanceof File)
    .map((file) => ({ name: file.name, uri: file.uri, size: file.size ?? null }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function useVault() {
  return useQuery({
    queryKey: VAULT_KEY,
    // Local disk, so it is never stale in the way a server response is.
    queryFn: async () => listVault(),
    staleTime: 0,
  });
}

/**
 * Downloads an authenticated PDF into the vault. The endpoint returns raw
 * bytes rather than the JSON envelope, so it cannot go through `request()`,
 * and linking at the URL would not work either — the browser carries no
 * access token.
 */
export async function downloadDocument(url: string, name: string): Promise<string> {
  const target = new File(vaultDirectory(), name);
  const origin = await resolveBaseUrl();

  const attempt = () =>
    File.downloadFileAsync(`${origin}${url}`, target, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
      idempotent: true,
    });

  try {
    const file = await attempt();
    return file.uri;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);

    // downloadFileAsync rejects on a non-2xx and puts the status in the
    // message; there is no status field to read.
    if (message.includes('401')) {
      // The 15-minute access token may have died while the student was
      // reading the list. One refresh, then one retry.
      await refreshSession();
      const file = await attempt();
      return file.uri;
    }

    if (message.includes('404')) throw new Error('That document is not available yet.');
    throw new Error('Could not download the document.');
  }
}

export function useSaveReceipt() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (invoiceId: string) =>
      downloadDocument(receiptPdfUrl(invoiceId), `receipt-${invoiceId}.pdf`),
    onSuccess: () => client.invalidateQueries({ queryKey: VAULT_KEY }),
  });
}

export async function shareDocument(uri: string): Promise<void> {
  if (!(await Sharing.isAvailableAsync())) return;
  await Sharing.shareAsync(uri, { mimeType: 'application/pdf', UTI: 'com.adobe.pdf' });
}

export function deleteDocument(uri: string): void {
  const file = new File(uri);
  if (file.exists) file.delete();
}
