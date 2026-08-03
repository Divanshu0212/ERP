import { Ionicons } from '@expo/vector-icons';
import { Link } from 'expo-router';
import { ScrollView, Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { Press } from '@/components/Press';
import { Body, Card, Label, Screen, Title } from '@/components/ui';
import { isActive, useOrders } from '@/features/canteen/useOrders';
import { INVOICES_KEY, useInvoices } from '@/features/fees/useInvoices';
import { useMyAllocation } from '@/features/hostel/useHostel';
import { pendingTotal } from '@/features/home/summary';
import { useUnreadCount } from '@/features/notifications/useInbox';
import { useSession } from '@/lib/auth/session';
import { cacheAge } from '@/lib/query/persister';

function Shortcut({
  href,
  icon,
  label,
  detail,
}: {
  href: string;
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  detail: string;
}) {
  return (
    <Link href={href} asChild>
      <Press accessibilityRole="link" accessibilityLabel={`${label}. ${detail}`}>
        <View className="min-h-touch flex-row items-center gap-3 rounded-card border border-surface-border bg-surface p-4">
          <Ionicons name={icon} size={22} color="#2c3ea8" />
          <View className="flex-1">
            <Text className="text-body text-ink">{label}</Text>
            <Text className="text-detail text-ink-muted">{detail}</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#656e7a" />
        </View>
      </Press>
    </Link>
  );
}

export default function StudentHome() {
  const user = useSession((s) => s.user);
  const { data: invoices } = useInvoices();
  const allocation = useMyAllocation();
  const unread = useUnreadCount();
  const { data: orders } = useOrders();
  const activeOrders = (orders?.results ?? []).filter(isActive).length;

  const pending = (invoices?.results ?? []).filter((i) => i.status === 'pending');
  const dues = pendingTotal(invoices?.results ?? []);

  return (
    <Screen>
      <OfflineBanner cachedAt={cacheAge(INVOICES_KEY)} />

      <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
        <View className="gap-1 px-4 pb-4 pt-2">
          <Title>{user?.email?.split('@')[0] ?? 'Student'}</Title>
          <Body muted>{user?.user_code}</Body>
        </View>

        <View className="gap-3 px-4">
          {/* Dues lead: it is the one item on this screen with a deadline. */}
          <Link href="/(student)/fees" asChild>
            <Press accessibilityRole="link" accessibilityLabel={`Fees, ₹${dues.toFixed(2)} pending`}>
              <Card className="gap-1">
                <Label>Pending dues</Label>
                <Money value={dues.toFixed(2)} className="text-display font-semibold text-ink" />
                <Body muted>
                  {pending.length === 0
                    ? 'Nothing due.'
                    : `${pending.length} unpaid ${pending.length === 1 ? 'invoice' : 'invoices'}`}
                </Body>
              </Card>
            </Press>
          </Link>

          <Shortcut
            href="/(student)/hostel"
            icon="bed"
            label="Hostel"
            detail={
              allocation.current ? allocation.current.room_name : 'No room allocated yet'
            }
          />

          <Shortcut
            href="/(student)/transport"
            icon="bus"
            label="Bus"
            detail="Book a seat on a campus route"
          />

          <Shortcut
            href="/(student)/attendance"
            icon="checkbox"
            label="Attendance"
            detail="Mark yourself present and see your percentage"
          />

          <Shortcut
            href="/(student)/pass"
            icon="qr-code"
            label="Bus pass"
            detail="Show your pass at the door"
          />

          <Shortcut
            href="/(student)/orders"
            icon="receipt"
            label="Orders"
            detail={
              activeOrders === 0
                ? 'Your canteen order history'
                : `${activeOrders} order${activeOrders === 1 ? '' : 's'} in progress`
            }
          />

          <Shortcut
            href="/(student)/notifications"
            icon="notifications"
            label="Notifications"
            detail={unread === 0 ? 'Nothing new' : `${unread} unread`}
          />

          <Shortcut
            href="/(student)/profile"
            icon="person"
            label="Profile"
            detail="Signed-in devices and sign out"
          />
        </View>
      </ScrollView>
    </Screen>
  );
}
