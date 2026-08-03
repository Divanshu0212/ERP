import type { Invoice } from '@api-types/index';
import { FlatList, Text, View } from 'react-native';

import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { useInvoices } from '@/features/fees/useInvoices';
import {
  type VaultEntry,
  deleteDocument,
  shareDocument,
  useSaveReceipt,
  useVault,
} from '@/features/vault/useVault';

function sizeLabel(bytes: number | null): string {
  if (bytes === null) return '';
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function DocumentRow({
  entry,
  onShare,
  onDelete,
}: {
  entry: VaultEntry;
  onShare: () => void;
  onDelete: () => void;
}) {
  return (
    <Card className="gap-3">
      <View className="gap-1">
        <Text className="text-body font-semibold text-ink">{entry.name}</Text>
        <Text className="text-detail text-ink-muted">{sizeLabel(entry.size)}</Text>
      </View>
      <View className="flex-row gap-3">
        <View className="flex-1">
          <Button label="Share" tone="quiet" onPress={onShare} />
        </View>
        <View className="flex-1">
          <Button label="Remove" tone="quiet" onPress={onDelete} />
        </View>
      </View>
    </Card>
  );
}

/**
 * Documents the student has saved to the phone. Reads the folder rather than
 * the API, so the list and the files both work with no network — which is the
 * only reason the feature exists.
 */
export default function VaultScreen() {
  const vault = useVault();
  const invoices = useInvoices();
  const save = useSaveReceipt();
  const snack = useSnackbar();

  const paid = (invoices.data?.results ?? []).filter(
    (invoice: Invoice) => invoice.status === 'paid',
  );
  const entries = vault.data ?? [];

  async function onSave(invoiceId: string) {
    try {
      await save.mutateAsync(invoiceId);
      snack.show('Saved to your phone.');
    } catch (error) {
      snack.show((error as Error).message, 'critical');
    }
  }

  return (
    <Screen>
      <FlatList
        data={entries}
        keyExtractor={(entry) => entry.uri}
        contentContainerClassName="gap-3 p-4"
        ListHeaderComponent={
          <View className="gap-4 pb-1">
            <Title>Documents</Title>
            <Body muted>
              Saved on this phone. These open with no signal — useful at a gate or a counter.
            </Body>

            {paid.length > 0 ? (
              <Card className="gap-3">
                <Label>Save a receipt</Label>
                {paid.map((invoice: Invoice) => (
                  <Button
                    key={invoice.id}
                    label={`${invoice.purpose} receipt`}
                    tone="quiet"
                    busy={save.isPending && save.variables === invoice.id}
                    onPress={() => void onSave(invoice.id)}
                  />
                ))}
              </Card>
            ) : null}

            <Label>On this phone</Label>
          </View>
        }
        renderItem={({ item }) => (
          <DocumentRow
            entry={item}
            onShare={() => void shareDocument(item.uri)}
            onDelete={() => {
              deleteDocument(item.uri);
              void vault.refetch();
            }}
          />
        )}
        ListEmptyComponent={
          <ListState
            loading={vault.isLoading}
            error={vault.isError ? 'Could not read saved documents.' : null}
            empty="Nothing saved yet."
            onRetry={() => void vault.refetch()}
          />
        }
      />
      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
