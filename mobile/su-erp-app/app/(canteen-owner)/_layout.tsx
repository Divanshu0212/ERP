import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';

/**
 * Three destinations: the live board the owner works off all service, the
 * scanner that completes a handoff, and the menu they adjust between rushes.
 */
export default function CanteenOwnerLayout() {
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
          title: 'Orders',
          tabBarIcon: ({ color, size }) => <Ionicons name="receipt" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="scan"
        options={{
          title: 'Scan',
          tabBarIcon: ({ color, size }) => <Ionicons name="scan" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="menu"
        options={{
          title: 'Menu',
          tabBarIcon: ({ color, size }) => <Ionicons name="fast-food" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
