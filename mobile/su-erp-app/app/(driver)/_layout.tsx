import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';

/**
 * Three destinations. A driver uses this phone mounted on a dashboard,
 * mid-route — anything beyond "run the trip", "who is on board", and "scan
 * them aboard" is a distraction at the wheel.
 */
export default function DriverLayout() {
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
          title: 'Trip',
          tabBarIcon: ({ color, size }) => <Ionicons name="bus" color={color} size={size} />,
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
        name="manifest"
        options={{
          title: 'Riders',
          tabBarIcon: ({ color, size }) => <Ionicons name="people" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
