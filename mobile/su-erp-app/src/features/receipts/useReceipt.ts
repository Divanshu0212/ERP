import { useMutation } from '@tanstack/react-query';
import { File, Paths } from 'expo-file-system';
import { readAsStringAsync } from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { useState } from 'react';

import { getAccessToken, refreshSession } from '@/lib/api/client';
import { resolveBaseUrl } from '@/lib/api/endpoint';
import { receiptPdfUrl } from '@/lib/api/finance';

/**
 * Downloads a receipt PDF to the cache directory.
 *
 * The endpoint is authenticated and returns raw bytes rather than the JSON
 * envelope, so it cannot go through `request()`. Linking straight at the URL
 * would not work either — the browser carries no access token.
 */
async function downloadReceipt(invoiceId: string): Promise<File> {
  const url = `${await resolveBaseUrl()}${receiptPdfUrl(invoiceId)}`;

  const attempt = () =>
    File.downloadFileAsync(url, new File(Paths.cache, `receipt-${invoiceId}.pdf`), {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
      idempotent: true,
    });

  try {
    return await attempt();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);

    // downloadFileAsync rejects on a non-2xx and puts the status in the
    // message; there is no status field to read.
    if (message.includes('401')) {
      // The 15-minute access token may have died while the student was
      // reading the list. One refresh, then one retry.
      await refreshSession();
      return attempt();
    }

    if (message.includes('404')) {
      throw new Error('No receipt for this invoice yet.');
    }

    throw new Error('Could not download the receipt.');
  }
}

/**
 * Opens receipts inside the app rather than handing them to an ACTION_VIEW
 * intent, which makes Android show an app chooser — this test device offers
 * twelve PDF handlers, so "view my receipt" would start with "pick an app".
 * Sharing stays available as a deliberate second action.
 */
export function useReceipt() {
  const [base64, setBase64] = useState<string | null>(null);
  const [uri, setUri] = useState<string | null>(null);

  const open = useMutation({
    mutationFn: async (invoiceId: string) => {
      const file = await downloadReceipt(invoiceId);
      const data = await readAsStringAsync(file.uri, { encoding: 'base64' });

      setUri(file.uri);
      setBase64(data);
      return file.uri;
    },
  });

  async function share(): Promise<void> {
    if (!uri) return;
    if (!(await Sharing.isAvailableAsync())) return;

    await Sharing.shareAsync(uri, {
      mimeType: 'application/pdf',
      dialogTitle: 'Fee receipt',
      UTI: 'com.adobe.pdf',
    });
  }

  return {
    base64,
    open,
    share,
    close: () => {
      setBase64(null);
      setUri(null);
    },
  };
}
