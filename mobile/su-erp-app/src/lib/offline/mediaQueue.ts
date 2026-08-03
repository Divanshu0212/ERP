// `expo-file-system/legacy` rather than the root import: SDK 54 replaced the
// function API with the `File`/`Directory` classes, and the one call needed
// here — delete a captured photo by its picker URI — is still cleanest through
// the legacy surface. Worth revisiting when the classes settle.
import { deleteAsync } from 'expo-file-system/legacy';

import { request } from '@/lib/api/client';

/**
 * Photos are queued separately from JSON mutations because they are large,
 * live on the filesystem rather than in the row, and must not be deleted
 * locally until the server has confirmed receipt.
 */
export interface PendingMedia {
  id: string;
  ticketId: string;
  uri: string;
  attempts: number;
}

export interface MediaStore {
  insert(item: PendingMedia): Promise<void>;
  all(): Promise<PendingMedia[]>;
  update(item: PendingMedia): Promise<void>;
  remove(id: string): Promise<void>;
}

export function createMemoryMediaStore(): MediaStore {
  let rows: PendingMedia[] = [];
  return {
    async insert(item) {
      rows.push(item);
    },
    async all() {
      return [...rows];
    },
    async update(item) {
      rows = rows.map((r) => (r.id === item.id ? item : r));
    },
    async remove(id) {
      rows = rows.filter((r) => r.id !== id);
    },
  };
}

let store: MediaStore = createMemoryMediaStore();

export function setMediaStore(next: MediaStore): void {
  store = next;
}

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function enqueueMedia(ticketId: string, uri: string): Promise<void> {
  await store.insert({ id: uuidv4(), ticketId, uri, attempts: 0 });
}

export async function replayMedia(): Promise<{ sent: number; failed: number }> {
  const rows = await store.all();
  let sent = 0;
  let failed = 0;

  for (const row of rows) {
    const form = new FormData();
    form.append('file', {
      uri: row.uri,
      name: 'evidence.jpg',
      type: 'image/jpeg',
    } as unknown as Blob);

    try {
      await request(`/api/v1/grievance/${row.ticketId}/media`, {
        method: 'POST',
        body: form,
        // Let the runtime set the multipart boundary — an explicit
        // application/json here would corrupt the upload.
        headers: {},
      });
      // Only now is it safe to drop the local copy.
      await deleteAsync(row.uri, { idempotent: true });
      await store.remove(row.id);
      sent += 1;
    } catch {
      await store.update({ ...row, attempts: row.attempts + 1 });
      failed += 1;
    }
  }

  return { sent, failed };
}
