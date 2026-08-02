import type { Invoice } from '@api-types/index';
import { FlatList, Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import {
  INVOICES_KEY,
  PaymentCancelled,
  useInvoices,
  usePayInvoice,
} from '@/features/fees/useInvoices';
import { pendingTotal } from '@/features/home/summary';
import { cacheAge } from '@/lib/query/persister';

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-caution-wash text-caution',
  paid: 'bg-positive-wash text-positive',
  failed: 'bg-critical-wash text-critical',
  cancelled: 'bg-surface-sunken text-ink-muted',
};

function StatusPill({ status }: { status: string }) {
  return (
    <View className={`self-start rounded-full px-2.5 py-1 ${STATUS_STYLE[status] ?? ''}`}>
      <Text className={`text-label uppercase ${STATUS_STYLE[status] ?? 'text-ink-muted'}`}>
        {status}
      </Text>
    </View>
  );
}

function InvoiceRow({
  invoice,
  onPay,
  busy,
}: {
  invoice: Invoice;
  onPay: (id: string) => void;
  busy: boolean;
}) {
  return (
    <Card className="mx-4 mb-3 gap-3">
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1 gap-1">
          <Text className="text-heading font-semibold text-ink">{invoice.purpose}</Text>
          <Text className="text-detail text-ink-faint">
            Raised {new Date(invoice.created_at).toLocaleDateString([], {
              day: 'numeric',
              month: 'short',
              year: 'numeric',
            })}
          </Text>
        </View>
        <Money value={invoice.amount} className="text-heading font-semibold text-ink" />
      </View>

      <StatusPill status={invoice.status} />

      {invoice.status === 'pending' ? (
        <Button label={busy ? 'Paying' : 'Pay now'} busy={busy} onPress={() => onPay(invoice.id)} />
      ) : null}
    </Card>
  );
}

export default function FeesScreen() {
  const { data, isLoading, isError, refetch, isRefetching } = useInvoices();
  const pay = usePayInvoice();
  const snack = useSnackbar();

  const invoices = data?.results ?? [];
  const pending = invoices.filter((i) => i.status === 'pending');
  const dues = pendingTotal(invoices);

  function onPay(invoiceId: string) {
    pay.mutate(invoiceId, {
      onSuccess: () => snack.show('Payment recorded.'),
      onError: (error) => {
        // Dismissing the fingerprint prompt is a choice, not a failure.
        if (error instanceof PaymentCancelled) return;
        snack.show((error as Error).message, 'critical');
      },
    });
  }

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(INVOICES_KEY)} />

      <FlatList
        data={invoices}
        keyExtractor={(i) => i.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        ListHeaderComponent={
          <View className="gap-4 px-4 pb-4 pt-2">
            <Title>Fees</Title>

            {/* The number a student opens this screen for, so it leads. */}
            <Card className="gap-1">
              <Label>Total pending</Label>
              <Money value={dues.toFixed(2)} className="text-display font-semibold text-ink" />
              <Body muted>
                {pending.length === 0
                  ? 'You are all paid up.'
                  : `${pending.length} unpaid ${pending.length === 1 ? 'invoice' : 'invoices'}`}
              </Body>
            </Card>
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={isLoading}
            error={isError ? 'Could not load your invoices.' : null}
            empty="No invoices yet."
            onRetry={refetch}
          />
        }
        renderItem={({ item }) => (
          <InvoiceRow
            invoice={item}
            onPay={onPay}
            busy={pay.isPending && pay.variables === item.id}
          />
        )}
      />

      <Snackbar message={snack.message} onDone={snack.clear} />
    </Screen>
  );
}
