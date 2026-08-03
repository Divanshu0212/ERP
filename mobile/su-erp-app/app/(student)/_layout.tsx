import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';

import { useUnreadCount } from '@/features/notifications/useInbox';

/**
 * Five destinations, not eight. Material caps a navigation bar at 3–5 on
 * compact width, and eight 48dp targets across a phone leaves each one too
 * narrow to hit reliably. Hostel, transport, and profile are reached from the
 * home screen, which is also where a student looks for them.
 */
export default function StudentLayout() {
  const unread = useUnreadCount();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: '#2c3ea8',
        tabBarInactiveTintColor: '#656e7a',
        tabBarStyle: { borderTopColor: '#e2e6ec' },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarIcon: ({ color, size }) => <Ionicons name="home" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="fees"
        options={{
          title: 'Fees',
          tabBarIcon: ({ color, size }) => <Ionicons name="card" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="canteen"
        options={{
          title: 'Canteen',
          tabBarIcon: ({ color, size }) => <Ionicons name="fast-food" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="notifications"
        options={{
          title: 'Alerts',
          tabBarBadge: unread > 0 ? unread : undefined,
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="notifications" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="grievance"
        options={{
          title: 'Help',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="alert-circle" color={color} size={size} />
          ),
        }}
      />

      {/* Reachable by route, not by tab. */}
      <Tabs.Screen name="hostel" options={{ href: null }} />
      <Tabs.Screen name="transport" options={{ href: null }} />
      <Tabs.Screen name="pass" options={{ href: null }} />
      <Tabs.Screen name="attendance" options={{ href: null }} />
      <Tabs.Screen name="orders" options={{ href: null }} />
      <Tabs.Screen name="profile" options={{ href: null }} />
    </Tabs>
  );
}
