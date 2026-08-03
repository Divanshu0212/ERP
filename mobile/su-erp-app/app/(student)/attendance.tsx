import type { CourseSummary } from '@api-types/index';
import { useState } from 'react';
import { FlatList, Text, TextInput, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { Snackbar, useSnackbar } from '@/components/Snackbar';
import { Body, Button, Card, Label, ListState, Screen, Title } from '@/components/ui';
import { useAttendanceSummary, useMarkAttendance } from '@/features/attendance/useAttendance';
import { useConnectivity } from '@/lib/net/connectivity';
import { cacheAge } from '@/lib/query/persister';

/** Below this, a student is usually barred from sitting the exam. */
const SHORTFALL_THRESHOLD = 75;

function SummaryRow({ course }: { course: CourseSummary }) {
  const short = course.percentage < SHORTFALL_THRESHOLD;

  return (
    <Card className="flex-row items-center justify-between">
      <View className="gap-1">
        <Text className="text-body font-semibold text-ink">{course.course_code}</Text>
        <Text className="text-detail text-ink-muted">
          {course.attended} of {course.held} classes
        </Text>
      </View>
      <Text
        className={`text-title font-semibold ${short ? 'text-critical' : 'text-ink'}`}
        accessibilityLabel={`${course.percentage} percent${short ? ', below requirement' : ''}`}
      >
        {course.percentage}%
      </Text>
    </Card>
  );
}

export default function AttendanceScreen() {
  const [sessionId, setSessionId] = useState('');
  const [code, setCode] = useState('');
  const summary = useAttendanceSummary();
  const mark = useMarkAttendance();
  const snackbar = useSnackbar();
  const online = useConnectivity((state) => state.online);

  async function onMark() {
    try {
      const result = await mark.mutateAsync({ sessionId: sessionId.trim(), code: code.trim() });
      snackbar.show(
        'queued' in result ? 'Saved — will send when you are back online' : 'Attendance marked',
      );
      setCode('');
      void summary.refetch();
    } catch (error) {
      // Verbatim: "You are not in the classroom" and "That code has expired"
      // are both actionable, and collapsing them into "failed" would leave
      // the student stuck with no idea which one to fix.
      snackbar.show((error as Error).message, 'critical');
    }
  }

  const ready = sessionId.trim().length > 0 && code.trim().length > 0;

  return (
    <Screen>
      <OfflineBanner />
      <FlatList
        data={summary.data ?? []}
        keyExtractor={(course) => course.course_code}
        contentContainerClassName="gap-3 p-4"
        ListHeaderComponent={
          <View className="gap-4 pb-1">
            <Title>Attendance</Title>

            <Card className="gap-3">
              <Label>Mark attendance</Label>

              <TextInput
                placeholder="Session ID from the board"
                placeholderTextColor="#656e7a"
                value={sessionId}
                onChangeText={setSessionId}
                autoCapitalize="none"
                autoCorrect={false}
                accessibilityLabel="Session ID"
                className="min-h-touch rounded-control border border-surface-border bg-surface px-3 text-body text-ink"
              />

              <TextInput
                placeholder="6-digit code"
                placeholderTextColor="#656e7a"
                value={code}
                onChangeText={setCode}
                keyboardType="number-pad"
                maxLength={6}
                accessibilityLabel="Six digit code"
                className="min-h-touch rounded-control border border-surface-border bg-surface px-3 text-body text-ink"
              />

              {/* Said before they tap, not after: the code rotates every 15
                  seconds, so a student who queues one will lose it. */}
              <Body muted>
                {online
                  ? 'Marks from inside the classroom, using the code on screen right now.'
                  : 'You are offline. A queued mark may expire before it sends.'}
              </Body>

              <Button
                label="Mark me present"
                onPress={() => void onMark()}
                busy={mark.isPending}
                disabled={!ready}
              />
            </Card>

            <Label>This semester</Label>
          </View>
        }
        renderItem={({ item }) => <SummaryRow course={item} />}
        ListEmptyComponent={
          <ListState
            loading={summary.isLoading}
            error={summary.isError ? 'Could not load your attendance.' : null}
            empty="No classes recorded yet."
            onRetry={() => void summary.refetch()}
          />
        }
        refreshing={summary.isRefetching}
        onRefresh={() => void summary.refetch()}
      />
      <Snackbar message={snackbar.message} onDone={snackbar.clear} />
    </Screen>
  );
}
