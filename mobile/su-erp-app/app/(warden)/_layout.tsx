import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';

/**
 * Three destinations, matching the three questions a warden actually has on
 * their feet: who lives here, what is broken, who is inside the gate.
 */
export default function WardenLayout() {
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
          title: 'Block',
          tabBarIcon: ({ color, size }) => <Ionicons name="business" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="grievances"
        options={{
          title: 'Grievances',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="alert-circle" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="visitors"
        options={{
          title: 'Visitors',
          tabBarIcon: ({ color, size }) => <Ionicons name="people" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
