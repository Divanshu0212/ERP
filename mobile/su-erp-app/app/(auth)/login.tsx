import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';

import { roleHome, useSession } from '@/lib/auth/session';

export default function LoginScreen() {
  const signIn = useSession((s) => s.signIn);
  const [institutionSlug, setInstitutionSlug] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await signIn(institutionSlug.trim(), email.trim(), password);
      const user = useSession.getState().user;
      if (user) router.replace(roleHome(user.role));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ flex: 1, justifyContent: 'center', padding: 24, gap: 12 }}>
      <Text style={{ fontSize: 28, fontWeight: '600', marginBottom: 12 }}>SU-ERP</Text>

      <TextInput
        placeholder="Institution"
        autoCapitalize="none"
        value={institutionSlug}
        onChangeText={setInstitutionSlug}
        style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
      />
      <TextInput
        placeholder="Email"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
        style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
      />
      <TextInput
        placeholder="Password"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
        style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
      />

      {error ? <Text style={{ color: '#b00020' }}>{error}</Text> : null}

      <Pressable
        onPress={submit}
        disabled={busy}
        style={{ backgroundColor: '#1d4ed8', borderRadius: 8, padding: 14, alignItems: 'center' }}
      >
        {busy ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={{ color: '#fff', fontWeight: '600' }}>Sign in</Text>
        )}
      </Pressable>
    </View>
  );
}
