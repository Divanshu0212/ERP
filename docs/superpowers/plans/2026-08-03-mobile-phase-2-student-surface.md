# Mobile Phase 2 — Student Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build every student-facing screen in the app — home, hostel, fees, canteen, transport, grievance, notifications, profile — on top of a persisted read cache that keeps the app usable offline.

**Architecture:** Each domain gets one `src/lib/api/<domain>.ts` module (pure HTTP, no React) and one `src/features/<domain>/` folder (hooks + screens). TanStack Query is persisted to MMKV so cached reads survive a cold start. Payments stay online-only and biometric-gated. No new backend endpoints — every call in this phase hits routes that already exist.

**Tech Stack:** Expo Router, TanStack Query + `@tanstack/query-async-storage-persister`, MMKV, `expo-local-authentication`, React Native Testing Library.

## Global Constraints

- Prerequisite: **Phase 1 is merged.** This plan consumes `request`, `ApiError` (`src/lib/api/client.ts`), `useSession` (`src/lib/auth/session.ts`), `enqueue`/`replay` (`src/lib/offline/queue.ts`), and the types in `shared/api-types/`.
- Spec: `docs/superpowers/specs/2026-08-02-mobile-app-design.md` §4, §5.1. Branch: `feat/mobile-app`.
- Every response arrives in the envelope `{success, data, message, errors}`; `request<T>()` already unwraps it — API modules return `data` directly and never re-check `success`.
- **Payments never queue.** `POST /api/v1/finance/pay` and `POST /api/v1/orders/checkout` fail loudly when offline (spec §4.2).
- Grievance creation is the only student mutation that queues in this phase.
- Cached reads must show their age. Any screen rendering from cache while offline shows the offline banner.
- List endpoints are paginated by `suerp_common.envelope.StandardPagination`: `data` is `{results, count, page, num_pages}`, not a bare array. Detail endpoints return the object directly.
- Money fields (`amount`, `price`, `total`, `unit_price`) arrive as **strings** from DRF `DecimalField`. Never do arithmetic on them without `Number()`; never render `toFixed` on a raw string.
- Commit as `Divanshu0212 <divanshubhargava026@gmail.com>`, no co-author trailer. Commit after every task.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/lib/api/hostel.ts` | allocations, room requests, complaints, leave requests |
| `src/lib/api/finance.ts` | invoices, pay |
| `src/lib/api/canteen.ts` | menu, orders, checkout |
| `src/lib/api/transport.ts` | routes, seats, bookings |
| `src/lib/api/grievance.ts` | tickets, comments |
| `src/lib/api/notify.ts` | inbox, mark-read |
| `src/lib/query/persister.ts` | MMKV-backed query persistence + cache-age reporting |
| `src/lib/net/connectivity.ts` | online/offline store, drives the banner and queue replay |
| `src/components/OfflineBanner.tsx` | shows connectivity and cache age |
| `src/components/Money.tsx` | renders a decimal string as currency |
| `src/features/<domain>/` | hooks + screens per domain |
| `app/(student)/` | tab layout and one route per domain |
| `shared/api-types/<domain>.ts` | shared request/response types per domain |

---

## Task 1: Connectivity store and offline banner

**Files:**
- Create: `mobile/su-erp-app/src/lib/net/connectivity.ts`
- Create: `mobile/su-erp-app/src/components/OfflineBanner.tsx`
- Create: `mobile/su-erp-app/src/lib/net/__tests__/connectivity.test.ts`

**Interfaces:**
- Consumes: `replay` from `src/lib/offline/queue.ts` (Phase 1 Task 11).
- Produces:
  - `useConnectivity()` Zustand store: `{ online: boolean; setOnline(v: boolean): void }`
  - `startConnectivityWatch(): () => void` — subscribes to NetInfo, replays the queue on regain, returns an unsubscribe
  - `<OfflineBanner />` component

- [ ] **Step 1: Install NetInfo**

Run: `cd mobile/su-erp-app && npx expo install @react-native-community/netinfo`

- [ ] **Step 2: Write the failing test**

Create `mobile/su-erp-app/src/lib/net/__tests__/connectivity.test.ts`:

```ts
import { startConnectivityWatch, useConnectivity } from '../connectivity';

let listener: ((state: { isConnected: boolean | null }) => void) | null = null;

jest.mock('@react-native-community/netinfo', () => ({
  addEventListener: jest.fn((cb) => {
    listener = cb;
    return () => {
      listener = null;
    };
  }),
}));
jest.mock('../../offline/queue', () => ({ replay: jest.fn(async () => ({ sent: 0, dropped: 0, failed: 0 })) }));

const { replay } = jest.requireMock('../../offline/queue');

beforeEach(() => {
  useConnectivity.setState({ online: true });
  replay.mockClear();
});

test('going offline flips the store', () => {
  startConnectivityWatch();
  listener?.({ isConnected: false });
  expect(useConnectivity.getState().online).toBe(false);
});

test('coming back online replays the queue', async () => {
  startConnectivityWatch();
  listener?.({ isConnected: false });
  listener?.({ isConnected: true });
  await Promise.resolve();
  expect(replay).toHaveBeenCalled();
});

test('staying online does not replay', async () => {
  startConnectivityWatch();
  listener?.({ isConnected: true });
  await Promise.resolve();
  expect(replay).not.toHaveBeenCalled();
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/net`
Expected: FAIL — `Cannot find module '../connectivity'`

- [ ] **Step 4: Write the store**

Create `mobile/su-erp-app/src/lib/net/connectivity.ts`:

```ts
import NetInfo from '@react-native-community/netinfo';
import { create } from 'zustand';

import { replay } from '../offline/queue';

interface ConnectivityState {
  online: boolean;
  setOnline(value: boolean): void;
}

export const useConnectivity = create<ConnectivityState>((set) => ({
  online: true,
  setOnline: (online) => set({ online }),
}));

/**
 * Watches connectivity and drains the mutation queue the moment the network
 * returns. Replaying on the transition (rather than on a timer) means a
 * warden who walks out of a basement sees their visitor-log entry land
 * within a second, with no manual retry.
 */
export function startConnectivityWatch(): () => void {
  return NetInfo.addEventListener((state) => {
    const online = state.isConnected !== false;
    const wasOnline = useConnectivity.getState().online;
    useConnectivity.getState().setOnline(online);

    if (online && !wasOnline) void replay();
  });
}
```

- [ ] **Step 5: Write the banner**

Create `mobile/su-erp-app/src/components/OfflineBanner.tsx`:

```tsx
import { Text, View } from 'react-native';

import { useConnectivity } from '@/lib/net/connectivity';

export function OfflineBanner({ cachedAt }: { cachedAt?: number }) {
  const online = useConnectivity((s) => s.online);
  if (online) return null;

  const stamp = cachedAt
    ? new Date(cachedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <View style={{ backgroundColor: '#78350f', paddingVertical: 6, paddingHorizontal: 12 }}>
      <Text style={{ color: '#fff', fontSize: 13 }}>
        {stamp ? `Offline — showing data from ${stamp}` : 'Offline'}
      </Text>
    </View>
  );
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd mobile/su-erp-app && npx jest src/lib/net`
Expected: all 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add mobile/su-erp-app/src/lib/net/ mobile/su-erp-app/src/components/OfflineBanner.tsx
git commit -m "feat(mobile): add connectivity watch that replays the queue on reconnect"
```

---

## Task 2: Persisted query cache

**Files:**
- Create: `mobile/su-erp-app/src/lib/query/persister.ts`
- Modify: `mobile/su-erp-app/app/_layout.tsx`
- Create: `mobile/su-erp-app/src/lib/query/__tests__/persister.test.ts`

**Interfaces:**
- Produces:
  - `mmkvPersister` — a `Persister` backed by MMKV
  - `queryClient` — the single app-wide client, moved out of `_layout.tsx`
  - `cacheAge(queryKey: unknown[]): number | undefined` — `dataUpdatedAt` for a key, feeding `<OfflineBanner cachedAt>`

- [ ] **Step 1: Install the persistence packages**

Run: `cd mobile/su-erp-app && npm install @tanstack/react-query-persist-client @tanstack/query-async-storage-persister`

- [ ] **Step 2: Write the failing test**

Create `mobile/su-erp-app/src/lib/query/__tests__/persister.test.ts`:

```ts
import { cacheAge, queryClient } from '../persister';

jest.mock('react-native-mmkv', () => ({
  MMKV: class {
    private store = new Map<string, string>();
    set(k: string, v: string) {
      this.store.set(k, v);
    }
    getString(k: string) {
      return this.store.get(k);
    }
    delete(k: string) {
      this.store.delete(k);
    }
  },
}));

beforeEach(() => queryClient.clear());

test('cacheAge is undefined for a key that was never fetched', () => {
  expect(cacheAge(['invoices'])).toBeUndefined();
});

test('cacheAge returns the update timestamp once data is cached', () => {
  queryClient.setQueryData(['invoices'], [{ id: '1' }]);
  expect(cacheAge(['invoices'])).toBeGreaterThan(0);
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/query`
Expected: FAIL — `Cannot find module '../persister'`

- [ ] **Step 4: Write the persister**

Create `mobile/su-erp-app/src/lib/query/persister.ts`:

```ts
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { QueryClient } from '@tanstack/react-query';
import { MMKV } from 'react-native-mmkv';

/**
 * Cached server reads, persisted so a cold start in a dead zone still shows
 * the student their timetable, dues, and allocation. This holds DATA ONLY —
 * tokens live in SecureStore (see lib/auth/storage.ts) and never here.
 */
const storage = new MMKV({ id: 'suerp.query-cache' });

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      gcTime: 1000 * 60 * 60 * 24 * 7,
    },
  },
});

export const mmkvPersister = createAsyncStoragePersister({
  storage: {
    getItem: async (key) => storage.getString(key) ?? null,
    setItem: async (key, value) => storage.set(key, value),
    removeItem: async (key) => storage.delete(key),
  },
  key: 'suerp.query-cache.v1',
});

/** When this key's data was last written — drives the offline banner stamp. */
export function cacheAge(queryKey: unknown[]): number | undefined {
  const state = queryClient.getQueryState(queryKey);
  return state?.dataUpdatedAt || undefined;
}
```

- [ ] **Step 5: Wire it into the root layout**

Replace the `QueryClientProvider` block in `mobile/su-erp-app/app/_layout.tsx` so the client comes from the persister module and persistence is active:

```tsx
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { Stack, router } from 'expo-router';
import { useEffect } from 'react';

import { setOnAuthFailure } from '@/lib/api/client';
import { useSession } from '@/lib/auth/session';
import { startConnectivityWatch } from '@/lib/net/connectivity';
import { mmkvPersister, queryClient } from '@/lib/query/persister';

export default function RootLayout() {
  useEffect(() => {
    setOnAuthFailure(() => {
      useSession.setState({ status: 'signed-out', user: null });
      router.replace('/(auth)/login');
    });
    return startConnectivityWatch();
  }, []);

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{ persister: mmkvPersister }}
    >
      <Stack screenOptions={{ headerShown: false }} />
    </PersistQueryClientProvider>
  );
}
```

- [ ] **Step 6: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest && npx tsc --noEmit`
Expected: every test PASSES, no type errors

- [ ] **Step 7: Commit**

```bash
git add mobile/su-erp-app/src/lib/query/ mobile/su-erp-app/app/_layout.tsx
git commit -m "feat(mobile): persist the query cache to MMKV for offline reads"
```

---

## Task 3: Shared domain types and the paginated helper

**Files:**
- Create: `shared/api-types/hostel.ts`, `finance.ts`, `canteen.ts`, `transport.ts`, `grievance.ts`, `notify.ts`
- Modify: `shared/api-types/envelope.ts`, `shared/api-types/index.ts`

**Interfaces:**
- Produces (consumed verbatim by Tasks 4–10):
  - `Paginated<T>` = `{ results: T[]; count: number; page: number; num_pages: number }`
  - `Invoice`, `Allocation`, `RoomRequest`, `MenuItem`, `Order`, `OrderItem`, `Route`, `Booking`, `Ticket`, `Notification`

- [ ] **Step 1: Add the pagination type**

Append to `shared/api-types/envelope.ts`:

```ts
/** List endpoints wrap results in this — see suerp_common StandardPagination. */
export interface Paginated<T> {
  results: T[];
  count: number;
  page: number;
  num_pages: number;
}
```

- [ ] **Step 2: Write the domain types**

Create `shared/api-types/finance.ts`:

```ts
/** DecimalField values arrive as strings — never do math on them directly. */
export type Decimal = string;

export type InvoiceStatus = 'pending' | 'paid' | 'failed' | 'cancelled';

export interface Invoice {
  id: string;
  student_user_code: string;
  amount: Decimal;
  purpose: string;
  status: InvoiceStatus;
  created_at: string;
}

export interface PayRequest {
  invoice_id: string;
  idempotency_key: string;
}
```

Create `shared/api-types/hostel.ts`:

```ts
export type AllocationStatus = 'pending' | 'confirmed' | 'released' | 'cancelled';
export type RoomRequestStatus = 'pending' | 'approved' | 'rejected';

export interface Allocation {
  id: string;
  student_user_code: string;
  room: string;
  status: AllocationStatus;
  created_at: string;
}

export interface RoomRequest {
  id: string;
  student_user_code: string;
  status: RoomRequestStatus;
  created_at: string;
}
```

Create `shared/api-types/canteen.ts`:

```ts
import type { Decimal } from './finance';

export type OrderStatus = 'placed' | 'preparing' | 'ready' | 'completed' | 'cancelled';

export interface MenuItem {
  id: string;
  name: string;
  price: Decimal;
  available: boolean;
  created_at: string;
}

export interface OrderItem {
  id: string;
  menu_item_id: string;
  name: string;
  quantity: number;
  unit_price: Decimal;
}

export interface Order {
  id: string;
  student_user_code: string;
  status: OrderStatus;
  total: Decimal;
  items: OrderItem[];
  created_at: string;
  updated_at: string;
}

export interface CartLine {
  menu_item_id: string;
  quantity: number;
}
```

Create `shared/api-types/transport.ts`:

```ts
export interface Route {
  id: string;
  name: string;
  start_point: string;
  end_point: string;
  created_at: string;
}

export type BookingStatus = 'booked' | 'cancelled';

export interface Booking {
  id: string;
  student_user_code: string;
  /** The backend field is seat_no, not seat_number — see transport/models.py. */
  seat_no: number;
  status: BookingStatus;
  created_at: string;
}

export interface BusSchedule {
  id: string;
  bus_no: string;
  driver_id: string;
  departure_time: string;
  capacity: number;
}
```

Create `shared/api-types/grievance.ts`:

```ts
/** Mirrors Ticket.Status in grievance/models.py — there is no 'closed'. */
export type TicketStatus = 'open' | 'escalated' | 'in_progress' | 'resolved';
export type Urgency = 'low' | 'medium' | 'high' | 'critical';

/** Categories are free-form at the DB level; these are the seeded labels. */
export type TicketCategory = 'hostel' | 'academic' | 'harassment' | 'it' | 'ragging';

export interface Ticket {
  id: string;
  raised_by: string;
  /** There is no subject field — category plus description is the whole ticket. */
  category: string;
  description: string;
  sentiment_score: number | null;
  urgency: Urgency | null;
  status: TicketStatus;
  assigned_to: string | null;
  created_at: string;
}
```

Create `shared/api-types/notify.ts`:

```ts
export interface Notification {
  id: string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
}
```

- [ ] **Step 3: Export them all**

Replace `shared/api-types/index.ts`:

```ts
export * from './auth';
export * from './canteen';
export * from './envelope';
export * from './finance';
export * from './grievance';
export * from './hostel';
export * from './notify';
export * from './transport';
```

- [ ] **Step 4: Verify the field names against the backend serializers**

Run:
```bash
grep -n "fields = " services/finance-service/billing/serializers.py services/canteen-service/canteen/serializers.py services/notification-service/notify/serializers.py services/hostel-service/hostel/serializers.py services/grievance-service/grievance/serializers.py
```
Expected: every field listed in the types above appears in the matching serializer. Correct the TypeScript to match the backend wherever they differ — the backend is the source of truth, and `status` string unions in particular must match the model's `TextChoices` values exactly.

- [ ] **Step 5: Typecheck and commit**

Run: `cd mobile/su-erp-app && npx tsc --noEmit`

```bash
git add shared/api-types/
git commit -m "feat(shared): add domain API types for the student surface"
```

---

## Task 4: Notifications inbox

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/notify.ts`
- Create: `mobile/su-erp-app/src/features/notifications/useInbox.ts`
- Create: `mobile/su-erp-app/app/(student)/notifications.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/notify.test.ts`

**Interfaces:**
- Consumes: `request` (Phase 1 Task 10), `Notification`, `Paginated` (Task 3), `queryClient` (Task 2).
- Produces: `fetchInbox(page?: number): Promise<Paginated<Notification>>`, `markRead(id: string): Promise<void>`, `useInbox()`, `useMarkRead()`.

This task establishes the pattern every later domain repeats: api module → hook → screen.

- [ ] **Step 1: Write the failing test**

Create `mobile/su-erp-app/src/lib/api/__tests__/notify.test.ts`:

```ts
import { fetchInbox, markRead } from '../notify';

jest.mock('../client', () => ({ request: jest.fn() }));
const { request } = jest.requireMock('../client');

beforeEach(() => request.mockReset());

test('fetchInbox hits the inbox endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchInbox();

  expect(request).toHaveBeenCalledWith('/api/v1/notify/inbox');
});

test('fetchInbox passes the page number', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 2, num_pages: 2 });

  await fetchInbox(2);

  expect(request).toHaveBeenCalledWith('/api/v1/notify/inbox?page=2');
});

test('markRead posts to the read endpoint', async () => {
  request.mockResolvedValue(undefined);

  await markRead('abc');

  expect(request).toHaveBeenCalledWith('/api/v1/notify/inbox/abc/read', { method: 'POST' });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/notify.test.ts`
Expected: FAIL — `Cannot find module '../notify'`

- [ ] **Step 3: Write the API module**

Create `mobile/su-erp-app/src/lib/api/notify.ts`:

```ts
import type { Notification, Paginated } from '@api-types/index';

import { request } from './client';

export function fetchInbox(page?: number): Promise<Paginated<Notification>> {
  const suffix = page ? `?page=${page}` : '';
  return request<Paginated<Notification>>(`/api/v1/notify/inbox${suffix}`);
}

export function markRead(id: string): Promise<void> {
  return request<void>(`/api/v1/notify/inbox/${id}/read`, { method: 'POST' });
}
```

- [ ] **Step 4: Write the hook**

Create `mobile/su-erp-app/src/features/notifications/useInbox.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchInbox, markRead } from '@/lib/api/notify';

export const INBOX_KEY = ['notify', 'inbox'];

export function useInbox() {
  return useQuery({ queryKey: INBOX_KEY, queryFn: () => fetchInbox() });
}

export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: markRead,
    onSuccess: () => client.invalidateQueries({ queryKey: INBOX_KEY }),
  });
}
```

- [ ] **Step 5: Write the screen**

Create `mobile/su-erp-app/app/(student)/notifications.tsx`:

```tsx
import { FlatList, Pressable, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { INBOX_KEY, useInbox, useMarkRead } from '@/features/notifications/useInbox';
import { cacheAge } from '@/lib/query/persister';

export default function NotificationsScreen() {
  const { data, isLoading, refetch, isRefetching } = useInbox();
  const markRead = useMarkRead();

  return (
    <View style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(INBOX_KEY)} />
      <FlatList
        data={data?.results ?? []}
        keyExtractor={(n) => n.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        ListEmptyComponent={
          <Text style={{ padding: 24 }}>{isLoading ? 'Loading…' : 'No notifications.'}</Text>
        }
        renderItem={({ item }) => (
          <Pressable
            onPress={() => !item.read && markRead.mutate(item.id)}
            style={{
              padding: 16,
              borderBottomWidth: 1,
              borderBottomColor: '#eee',
              opacity: item.read ? 0.6 : 1,
            }}
          >
            <Text style={{ fontWeight: item.read ? '400' : '600' }}>{item.title}</Text>
            <Text style={{ color: '#555', marginTop: 4 }}>{item.body}</Text>
          </Pressable>
        )}
      />
    </View>
  );
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/notify.test.ts && npx tsc --noEmit`
Expected: 3 tests PASS, no type errors

- [ ] **Step 7: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/notify.ts mobile/su-erp-app/src/features/notifications/ mobile/su-erp-app/app/\(student\)/notifications.tsx mobile/su-erp-app/src/lib/api/__tests__/notify.test.ts
git commit -m "feat(mobile): add notifications inbox with mark-read"
```

---

## Task 5: Fees — invoice list and payment

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/finance.ts`
- Create: `mobile/su-erp-app/src/lib/device/biometrics.ts`
- Create: `mobile/su-erp-app/src/features/fees/useInvoices.ts`
- Create: `mobile/su-erp-app/app/(student)/fees.tsx`
- Create: `mobile/su-erp-app/src/components/Money.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/finance.test.ts`

**Interfaces:**
- Consumes: `request`, `ApiError`, `Invoice`, `Paginated`, `useConnectivity` (Task 1).
- Produces:
  - `fetchInvoices(): Promise<Paginated<Invoice>>`
  - `payInvoice(invoiceId: string): Promise<void>` — generates its own `idempotency_key`, throws `OfflineError` when offline
  - `class OfflineError extends Error`
  - `authenticate(reason: string): Promise<boolean>` in `lib/device/biometrics.ts`
  - `<Money value={decimalString} />`

- [ ] **Step 1: Write the failing tests**

Create `mobile/su-erp-app/src/lib/api/__tests__/finance.test.ts`:

```ts
import { useConnectivity } from '../../net/connectivity';
import { OfflineError, fetchInvoices, payInvoice } from '../finance';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));
const { request } = jest.requireMock('../client');

beforeEach(() => {
  request.mockReset();
  useConnectivity.setState({ online: true });
});

test('fetchInvoices hits the invoices endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchInvoices();

  expect(request).toHaveBeenCalledWith('/api/v1/finance/invoices');
});

test('payInvoice posts an idempotency key with the invoice id', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-1');

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.invoice_id).toBe('inv-1');
  expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
});

test('payInvoice refuses to run offline instead of queueing', async () => {
  useConnectivity.setState({ online: false });

  await expect(payInvoice('inv-1')).rejects.toBeInstanceOf(OfflineError);
  expect(request).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/finance.test.ts`
Expected: FAIL — `Cannot find module '../finance'`

- [ ] **Step 3: Write the API module**

Create `mobile/su-erp-app/src/lib/api/finance.ts`:

```ts
import type { Invoice, Paginated } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';

/** Raised instead of queueing, for mutations that must never fire late. */
export class OfflineError extends Error {
  constructor(message = 'You are offline. Connect to the network and try again.') {
    super(message);
    this.name = 'OfflineError';
  }
}

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function fetchInvoices(): Promise<Paginated<Invoice>> {
  return request<Paginated<Invoice>>('/api/v1/finance/invoices');
}

/**
 * Deliberately NOT queueable. A fee payment that silently fires an hour
 * after the student walked away is worse than one that fails in front of
 * them — see the spec's offline rules. The idempotency_key still guards
 * against a double tap or a retried request.
 */
export async function payInvoice(invoiceId: string): Promise<void> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  await request<void>('/api/v1/finance/pay', {
    method: 'POST',
    body: JSON.stringify({ invoice_id: invoiceId, idempotency_key: uuidv4() }),
  });
}
```

- [ ] **Step 4: Write the biometrics module**

Create `mobile/su-erp-app/src/lib/device/biometrics.ts`:

```ts
import * as LocalAuthentication from 'expo-local-authentication';

/**
 * Biometric data never leaves the device and is never sent to the server —
 * this is a local gate in front of a payment, not an authentication factor
 * the backend sees. The server's protection against a bypassed client
 * remains the idempotency key on /pay.
 *
 * A device with no enrolled biometrics returns true: locking a student out
 * of paying their fees because their phone has no fingerprint reader would
 * be worse than the gate is worth.
 */
export async function authenticate(reason: string): Promise<boolean> {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  const enrolled = await LocalAuthentication.isEnrolledAsync();
  if (!hasHardware || !enrolled) return true;

  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: reason,
    disableDeviceFallback: false,
  });
  return result.success;
}
```

- [ ] **Step 5: Write the Money component**

Create `mobile/su-erp-app/src/components/Money.tsx`:

```tsx
import { Text, type TextProps } from 'react-native';

/** Renders a DRF DecimalField string. Never does arithmetic on it. */
export function Money({ value, ...props }: { value: string } & TextProps) {
  const amount = Number(value);
  const display = Number.isFinite(amount) ? amount.toFixed(2) : value;
  return <Text {...props}>₹{display}</Text>;
}
```

- [ ] **Step 6: Write the hook and screen**

Create `mobile/su-erp-app/src/features/fees/useInvoices.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchInvoices, payInvoice } from '@/lib/api/finance';
import { authenticate } from '@/lib/device/biometrics';

export const INVOICES_KEY = ['finance', 'invoices'];

export function useInvoices() {
  return useQuery({ queryKey: INVOICES_KEY, queryFn: fetchInvoices });
}

export function usePayInvoice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (invoiceId: string) => {
      const approved = await authenticate('Confirm your fee payment');
      if (!approved) throw new Error('Payment cancelled.');
      return payInvoice(invoiceId);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: INVOICES_KEY }),
  });
}
```

Create `mobile/su-erp-app/app/(student)/fees.tsx`:

```tsx
import { Alert, FlatList, Pressable, Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { INVOICES_KEY, useInvoices, usePayInvoice } from '@/features/fees/useInvoices';
import { cacheAge } from '@/lib/query/persister';

export default function FeesScreen() {
  const { data, isLoading, refetch, isRefetching } = useInvoices();
  const pay = usePayInvoice();

  function onPay(invoiceId: string) {
    pay.mutate(invoiceId, {
      onError: (error) => Alert.alert('Payment failed', (error as Error).message),
      onSuccess: () => Alert.alert('Paid', 'Your payment was recorded.'),
    });
  }

  return (
    <View style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(INVOICES_KEY)} />
      <FlatList
        data={data?.results ?? []}
        keyExtractor={(i) => i.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        ListEmptyComponent={
          <Text style={{ padding: 24 }}>{isLoading ? 'Loading…' : 'No invoices.'}</Text>
        }
        renderItem={({ item }) => (
          <View style={{ padding: 16, borderBottomWidth: 1, borderBottomColor: '#eee', gap: 6 }}>
            <Text style={{ fontWeight: '600' }}>{item.purpose}</Text>
            <Money value={item.amount} />
            <Text style={{ color: '#666' }}>{item.status}</Text>
            {item.status === 'pending' ? (
              <Pressable
                disabled={pay.isPending}
                onPress={() => onPay(item.id)}
                style={{
                  backgroundColor: '#1d4ed8',
                  borderRadius: 8,
                  padding: 10,
                  alignItems: 'center',
                }}
              >
                <Text style={{ color: '#fff', fontWeight: '600' }}>
                  {pay.isPending ? 'Paying…' : 'Pay now'}
                </Text>
              </Pressable>
            ) : null}
          </View>
        )}
      />
    </View>
  );
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/finance.test.ts && npx tsc --noEmit`
Expected: 3 tests PASS, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/finance.ts mobile/su-erp-app/src/lib/device/biometrics.ts mobile/su-erp-app/src/components/Money.tsx mobile/su-erp-app/src/features/fees/ mobile/su-erp-app/app/\(student\)/fees.tsx mobile/su-erp-app/src/lib/api/__tests__/finance.test.ts
git commit -m "feat(mobile): add fees screen with biometric-gated online-only payment"
```

---

## Task 6: Canteen — menu, cart, checkout, order status

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/canteen.ts`
- Create: `mobile/su-erp-app/src/features/canteen/useCart.ts`, `useMenu.ts`, `useOrders.ts`
- Create: `mobile/su-erp-app/app/(student)/canteen.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/canteen.test.ts`
- Create: `mobile/su-erp-app/src/features/canteen/__tests__/useCart.test.ts`

**Interfaces:**
- Consumes: `request`, `OfflineError` (Task 5), `MenuItem`, `Order`, `CartLine`, `Paginated`.
- Produces:
  - `fetchMenu(): Promise<Paginated<MenuItem>>`
  - `fetchOrders(): Promise<Paginated<Order>>`
  - `placeOrder(items: CartLine[]): Promise<Order>` — online-only, throws `OfflineError`
  - `useCart()` Zustand store: `{ lines: Record<string, number>; add(id): void; remove(id): void; clear(): void; toLines(): CartLine[]; count(): number }`

- [ ] **Step 1: Write the failing tests**

Create `mobile/su-erp-app/src/lib/api/__tests__/canteen.test.ts`:

```ts
import { useConnectivity } from '../../net/connectivity';
import { placeOrder } from '../canteen';
import { OfflineError } from '../finance';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));
const { request } = jest.requireMock('../client');

beforeEach(() => {
  request.mockReset();
  useConnectivity.setState({ online: true });
});

test('placeOrder posts the cart lines', async () => {
  request.mockResolvedValue({ id: 'o1' });

  await placeOrder([{ menu_item_id: 'm1', quantity: 2 }]);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.items).toEqual([{ menu_item_id: 'm1', quantity: 2 }]);
});

test('placeOrder refuses to run offline', async () => {
  useConnectivity.setState({ online: false });

  await expect(placeOrder([{ menu_item_id: 'm1', quantity: 1 }])).rejects.toBeInstanceOf(
    OfflineError,
  );
});
```

Create `mobile/su-erp-app/src/features/canteen/__tests__/useCart.test.ts`:

```ts
import { useCart } from '../useCart';

beforeEach(() => useCart.getState().clear());

test('adding an item sets quantity to one', () => {
  useCart.getState().add('m1');
  expect(useCart.getState().lines.m1).toBe(1);
});

test('adding the same item twice increments it', () => {
  useCart.getState().add('m1');
  useCart.getState().add('m1');
  expect(useCart.getState().lines.m1).toBe(2);
});

test('removing decrements and drops the line at zero', () => {
  useCart.getState().add('m1');
  useCart.getState().remove('m1');
  expect(useCart.getState().lines.m1).toBeUndefined();
});

test('toLines converts the map to the request shape', () => {
  useCart.getState().add('m1');
  useCart.getState().add('m2');
  useCart.getState().add('m2');

  expect(useCart.getState().toLines()).toEqual([
    { menu_item_id: 'm1', quantity: 1 },
    { menu_item_id: 'm2', quantity: 2 },
  ]);
});

test('count sums every quantity', () => {
  useCart.getState().add('m1');
  useCart.getState().add('m2');
  useCart.getState().add('m2');
  expect(useCart.getState().count()).toBe(3);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/canteen.test.ts src/features/canteen`
Expected: FAIL — both modules missing

- [ ] **Step 3: Write the API module**

Create `mobile/su-erp-app/src/lib/api/canteen.ts`:

```ts
import type { CartLine, MenuItem, Order, Paginated } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';
import { OfflineError } from './finance';

export function fetchMenu(): Promise<Paginated<MenuItem>> {
  return request<Paginated<MenuItem>>('/api/v1/menu-items/');
}

export function fetchOrders(): Promise<Paginated<Order>> {
  return request<Paginated<Order>>('/api/v1/orders/');
}

/** Money changes hands here, so this never queues — same rule as payInvoice. */
export async function placeOrder(items: CartLine[]): Promise<Order> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  return request<Order>('/api/v1/orders/', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}
```

- [ ] **Step 4: Write the cart store**

Create `mobile/su-erp-app/src/features/canteen/useCart.ts`:

```ts
import type { CartLine } from '@api-types/index';
import { create } from 'zustand';

interface CartState {
  lines: Record<string, number>;
  add(menuItemId: string): void;
  remove(menuItemId: string): void;
  clear(): void;
  toLines(): CartLine[];
  count(): number;
}

export const useCart = create<CartState>((set, get) => ({
  lines: {},

  add: (id) => set((s) => ({ lines: { ...s.lines, [id]: (s.lines[id] ?? 0) + 1 } })),

  remove: (id) =>
    set((s) => {
      const next = (s.lines[id] ?? 0) - 1;
      const lines = { ...s.lines };
      if (next <= 0) delete lines[id];
      else lines[id] = next;
      return { lines };
    }),

  clear: () => set({ lines: {} }),

  toLines: () =>
    Object.entries(get().lines).map(([menu_item_id, quantity]) => ({ menu_item_id, quantity })),

  count: () => Object.values(get().lines).reduce((sum, n) => sum + n, 0),
}));
```

- [ ] **Step 5: Write the query hooks**

Create `mobile/su-erp-app/src/features/canteen/useMenu.ts`:

```ts
import { useQuery } from '@tanstack/react-query';

import { fetchMenu } from '@/lib/api/canteen';

export const MENU_KEY = ['canteen', 'menu'];

export function useMenu() {
  return useQuery({ queryKey: MENU_KEY, queryFn: fetchMenu });
}
```

Create `mobile/su-erp-app/src/features/canteen/useOrders.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchOrders, placeOrder } from '@/lib/api/canteen';

import { useCart } from './useCart';

export const ORDERS_KEY = ['canteen', 'orders'];

export function useOrders() {
  return useQuery({
    queryKey: ORDERS_KEY,
    queryFn: fetchOrders,
    // An in-flight order changes state in the kitchen, not on this device —
    // poll while the screen is open so "ready" appears without a manual pull.
    refetchInterval: 15_000,
  });
}

export function usePlaceOrder() {
  const client = useQueryClient();
  const clearCart = useCart((s) => s.clear);

  return useMutation({
    mutationFn: placeOrder,
    onSuccess: () => {
      clearCart();
      void client.invalidateQueries({ queryKey: ORDERS_KEY });
    },
  });
}
```

- [ ] **Step 6: Write the screen**

Create `mobile/su-erp-app/app/(student)/canteen.tsx`:

```tsx
import { Alert, FlatList, Pressable, Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { useCart } from '@/features/canteen/useCart';
import { MENU_KEY, useMenu } from '@/features/canteen/useMenu';
import { useOrders, usePlaceOrder } from '@/features/canteen/useOrders';
import { cacheAge } from '@/lib/query/persister';

export default function CanteenScreen() {
  const { data: menu, isLoading } = useMenu();
  const { data: orders } = useOrders();
  const cart = useCart();
  const place = usePlaceOrder();

  const active = (orders?.results ?? []).filter(
    (o) => o.status !== 'completed' && o.status !== 'cancelled',
  );

  function checkout() {
    place.mutate(cart.toLines(), {
      onError: (e) => Alert.alert('Order failed', (e as Error).message),
    });
  }

  return (
    <View style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(MENU_KEY)} />

      {active.map((order) => (
        <View key={order.id} style={{ padding: 12, backgroundColor: '#eef2ff' }}>
          <Text style={{ fontWeight: '600' }}>Order {order.status}</Text>
          <Money value={order.total} />
        </View>
      ))}

      <FlatList
        data={menu?.results ?? []}
        keyExtractor={(m) => m.id}
        ListEmptyComponent={
          <Text style={{ padding: 24 }}>{isLoading ? 'Loading…' : 'Menu is empty.'}</Text>
        }
        renderItem={({ item }) => (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              padding: 16,
              borderBottomWidth: 1,
              borderBottomColor: '#eee',
              gap: 12,
            }}
          >
            <View style={{ flex: 1 }}>
              <Text style={{ fontWeight: '600' }}>{item.name}</Text>
              <Money value={item.price} />
            </View>
            {item.available ? (
              <>
                <Pressable onPress={() => cart.remove(item.id)}>
                  <Text style={{ fontSize: 22, paddingHorizontal: 10 }}>−</Text>
                </Pressable>
                <Text>{cart.lines[item.id] ?? 0}</Text>
                <Pressable onPress={() => cart.add(item.id)}>
                  <Text style={{ fontSize: 22, paddingHorizontal: 10 }}>+</Text>
                </Pressable>
              </>
            ) : (
              <Text style={{ color: '#999' }}>Unavailable</Text>
            )}
          </View>
        )}
      />

      {cart.count() > 0 ? (
        <Pressable
          onPress={checkout}
          disabled={place.isPending}
          style={{ backgroundColor: '#1d4ed8', padding: 16, alignItems: 'center' }}
        >
          <Text style={{ color: '#fff', fontWeight: '600' }}>
            {place.isPending ? 'Placing…' : `Place order (${cart.count()})`}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/canteen.test.ts src/features/canteen && npx tsc --noEmit`
Expected: 7 tests PASS, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/canteen.ts mobile/su-erp-app/src/features/canteen/ mobile/su-erp-app/app/\(student\)/canteen.tsx mobile/su-erp-app/src/lib/api/__tests__/canteen.test.ts
git commit -m "feat(mobile): add canteen menu, cart, and live order status"
```

---

## Task 7: Hostel — allocation and room requests

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/hostel.ts`
- Create: `mobile/su-erp-app/src/features/hostel/useHostel.ts`
- Create: `mobile/su-erp-app/app/(student)/hostel.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/hostel.test.ts`

**Interfaces:**
- Consumes: `request`, `Allocation`, `RoomRequest`, `Paginated`.
- Produces: `fetchMyAllocations()`, `fetchMyRoomRequests()`, `createRoomRequest(preferences)`.

- [ ] **Step 1: Confirm the endpoint shapes**

Run: `grep -n "path(" services/hostel-service/hostel/urls.py` and `grep -n "class MyRoomRequestsView\|class RoomRequestListCreateView\|class AllocationListView" -A 20 services/hostel-service/hostel/views.py`
Record: the exact paths and whether `MyRoomRequestsView` filters by the caller's `sub` claim. Use those paths verbatim below.

- [ ] **Step 2: Write the failing test**

Create `mobile/su-erp-app/src/lib/api/__tests__/hostel.test.ts`:

```ts
import { createRoomRequest, fetchMyRoomRequests } from '../hostel';

jest.mock('../client', () => ({ request: jest.fn() }));
const { request } = jest.requireMock('../client');

beforeEach(() => request.mockReset());

test('fetchMyRoomRequests hits the mine endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchMyRoomRequests();

  expect(request).toHaveBeenCalledWith('/api/v1/hostel/room-requests/mine');
});

test('createRoomRequest posts the preference payload', async () => {
  request.mockResolvedValue({ id: 'r1' });

  await createRoomRequest({ preferred_block: 'A' });

  expect(request).toHaveBeenCalledWith(
    '/api/v1/hostel/room-requests',
    expect.objectContaining({ method: 'POST' }),
  );
});
```

If Step 1 showed different paths, change both the test and the module to match — the backend wins.

- [ ] **Step 3: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/hostel.test.ts`
Expected: FAIL — module missing

- [ ] **Step 4: Write the API module**

Create `mobile/su-erp-app/src/lib/api/hostel.ts`:

```ts
import type { Allocation, Paginated, RoomRequest } from '@api-types/index';

import { request } from './client';

export function fetchMyAllocations(): Promise<Paginated<Allocation>> {
  return request<Paginated<Allocation>>('/api/v1/hostel/allocations');
}

export function fetchMyRoomRequests(): Promise<Paginated<RoomRequest>> {
  return request<Paginated<RoomRequest>>('/api/v1/hostel/room-requests/mine');
}

export function createRoomRequest(preferences: Record<string, string>): Promise<RoomRequest> {
  return request<RoomRequest>('/api/v1/hostel/room-requests', {
    method: 'POST',
    body: JSON.stringify(preferences),
  });
}
```

- [ ] **Step 5: Write the hook**

Create `mobile/su-erp-app/src/features/hostel/useHostel.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { createRoomRequest, fetchMyAllocations, fetchMyRoomRequests } from '@/lib/api/hostel';

export const ALLOCATIONS_KEY = ['hostel', 'allocations'];
export const ROOM_REQUESTS_KEY = ['hostel', 'room-requests'];

export function useMyAllocation() {
  return useQuery({ queryKey: ALLOCATIONS_KEY, queryFn: fetchMyAllocations });
}

export function useMyRoomRequests() {
  return useQuery({ queryKey: ROOM_REQUESTS_KEY, queryFn: fetchMyRoomRequests });
}

export function useRequestRoom() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createRoomRequest,
    onSuccess: () => client.invalidateQueries({ queryKey: ROOM_REQUESTS_KEY }),
  });
}
```

- [ ] **Step 6: Write the screen**

Create `mobile/su-erp-app/app/(student)/hostel.tsx`:

```tsx
import { Alert, Pressable, ScrollView, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import {
  ALLOCATIONS_KEY,
  useMyAllocation,
  useMyRoomRequests,
  useRequestRoom,
} from '@/features/hostel/useHostel';
import { cacheAge } from '@/lib/query/persister';

export default function HostelScreen() {
  const { data: allocations } = useMyAllocation();
  const { data: requests } = useMyRoomRequests();
  const requestRoom = useRequestRoom();

  const current = (allocations?.results ?? []).find((a) => a.status === 'confirmed');
  const pending = (requests?.results ?? []).some((r) => r.status === 'pending');

  return (
    <ScrollView style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(ALLOCATIONS_KEY)} />

      <View style={{ padding: 16, gap: 8 }}>
        <Text style={{ fontSize: 18, fontWeight: '600' }}>My room</Text>
        {current ? (
          <Text>Room {current.room} — {current.status}</Text>
        ) : (
          <Text style={{ color: '#666' }}>No confirmed allocation yet.</Text>
        )}
      </View>

      <View style={{ padding: 16, gap: 8 }}>
        <Text style={{ fontSize: 18, fontWeight: '600' }}>Room requests</Text>
        {(requests?.results ?? []).map((r) => (
          <Text key={r.id}>
            {new Date(r.created_at).toLocaleDateString()} — {r.status}
          </Text>
        ))}

        {!current && !pending ? (
          <Pressable
            onPress={() =>
              requestRoom.mutate(
                {},
                { onError: (e) => Alert.alert('Request failed', (e as Error).message) },
              )
            }
            style={{ backgroundColor: '#1d4ed8', borderRadius: 8, padding: 14, alignItems: 'center' }}
          >
            <Text style={{ color: '#fff', fontWeight: '600' }}>Request a room</Text>
          </Pressable>
        ) : null}
      </View>
    </ScrollView>
  );
}
```

- [ ] **Step 7: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/hostel.test.ts && npx tsc --noEmit`
Expected: 2 tests PASS, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/hostel.ts mobile/su-erp-app/src/features/hostel/ mobile/su-erp-app/app/\(student\)/hostel.tsx mobile/su-erp-app/src/lib/api/__tests__/hostel.test.ts
git commit -m "feat(mobile): add hostel allocation and room request screen"
```

---

## Task 8: Transport — routes, seats, booking

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/transport.ts`
- Create: `mobile/su-erp-app/src/features/transport/useTransport.ts`
- Create: `mobile/su-erp-app/app/(student)/transport.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/transport.test.ts`

**Interfaces:**
- Consumes: `request`, `Route`, `Booking`, `Paginated`, `OfflineError`.
- Produces: `fetchRoutes()`, `fetchSeats(routeId)`, `bookSeat(routeId, seatNumber)` — online-only (a seat is a scarce resource; a queued booking would claim a seat someone else already took).

- [ ] **Step 1: Confirm the booking payload the backend expects**

Run: `grep -n "class BookingCreateView" -A 30 services/transport-service/transport/views.py`
Record whether the body keys are `schedule_id`/`seat_no` (likely, given `Booking.schedule` and `Booking.seat_no` in the model) or something else, and whether `idempotency_key` is accepted. Use those exact keys in the module below, adjusting the test to match. The backend is the source of truth.

- [ ] **Step 2: Write the failing test**

Create `mobile/su-erp-app/src/lib/api/__tests__/transport.test.ts`:

```ts
import { useConnectivity } from '../../net/connectivity';
import { OfflineError } from '../finance';
import { bookSeat, fetchRoutes, fetchSeats } from '../transport';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));
const { request } = jest.requireMock('../client');

beforeEach(() => {
  request.mockReset();
  useConnectivity.setState({ online: true });
});

test('fetchRoutes hits the routes endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });
  await fetchRoutes();
  expect(request).toHaveBeenCalledWith('/api/v1/transport/routes');
});

test('fetchSeats hits the per-route seats endpoint', async () => {
  request.mockResolvedValue({ taken: [], schedules: [] });
  await fetchSeats('r1');
  expect(request).toHaveBeenCalledWith('/api/v1/transport/routes/r1/seats');
});

test('bookSeat posts the schedule id and seat number', async () => {
  request.mockResolvedValue({ id: 'b1' });

  await bookSeat('sched-1', 4);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body).toEqual({ schedule_id: 'sched-1', seat_no: 4 });
});

test('bookSeat refuses to run offline', async () => {
  useConnectivity.setState({ online: false });
  await expect(bookSeat('sched-1', 4)).rejects.toBeInstanceOf(OfflineError);
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/transport.test.ts`
Expected: FAIL — module missing

- [ ] **Step 4: Write the API module**

Create `mobile/su-erp-app/src/lib/api/transport.ts`:

```ts
import type { Booking, BusSchedule, Paginated, Route } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';
import { OfflineError } from './finance';

export function fetchRoutes(): Promise<Paginated<Route>> {
  return request<Paginated<Route>>('/api/v1/transport/routes');
}

/**
 * Per-route seat availability. Confirm the exact response shape in Step 1 —
 * it must supply both the schedules on this route and which seats are gone.
 */
export function fetchSeats(
  routeId: string,
): Promise<{ taken: number[]; schedules: BusSchedule[] }> {
  return request<{ taken: number[]; schedules: BusSchedule[] }>(
    `/api/v1/transport/routes/${routeId}/seats`,
  );
}

/**
 * Online-only. A seat is a scarce resource with a DB-level uniqueness
 * constraint behind it — a booking replayed twenty minutes later would be
 * claiming a seat that is very likely already gone, and the student would
 * believe they had one.
 */
export async function bookSeat(scheduleId: string, seatNo: number): Promise<Booking> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  return request<Booking>('/api/v1/transport/bookings', {
    method: 'POST',
    body: JSON.stringify({ schedule_id: scheduleId, seat_no: seatNo }),
  });
}
```

- [ ] **Step 5: Write the hook**

Create `mobile/su-erp-app/src/features/transport/useTransport.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { bookSeat, fetchRoutes, fetchSeats } from '@/lib/api/transport';

export const ROUTES_KEY = ['transport', 'routes'];
export const seatsKey = (routeId: string) => ['transport', 'seats', routeId];

export function useRoutes() {
  return useQuery({ queryKey: ROUTES_KEY, queryFn: fetchRoutes });
}

export function useSeats(routeId: string | null) {
  return useQuery({
    queryKey: seatsKey(routeId ?? ''),
    queryFn: () => fetchSeats(routeId as string),
    enabled: Boolean(routeId),
  });
}

/**
 * A booking belongs to a BusSchedule (a specific bus at a specific time),
 * not to a Route — see transport/models.py Booking.schedule. The route
 * selection above narrows which schedules to show; the schedule is what
 * actually gets booked.
 */
export function useBookSeat(scheduleId: string | null, routeId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (seatNo: number) => bookSeat(scheduleId as string, seatNo),
    onSuccess: () => client.invalidateQueries({ queryKey: seatsKey(routeId ?? '') }),
  });
}
```

- [ ] **Step 6: Write the screen**

Create `mobile/su-erp-app/app/(student)/transport.tsx`:

```tsx
import { useState } from 'react';
import { Alert, Pressable, ScrollView, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { ROUTES_KEY, useBookSeat, useRoutes, useSeats } from '@/features/transport/useTransport';
import { cacheAge } from '@/lib/query/persister';

const SEAT_COUNT = 40;

export default function TransportScreen() {
  const [routeId, setRouteId] = useState<string | null>(null);
  const [scheduleId, setScheduleId] = useState<string | null>(null);
  const { data: routes } = useRoutes();
  const { data: seats } = useSeats(routeId);
  const book = useBookSeat(scheduleId, routeId);

  const taken = new Set(seats?.taken ?? []);

  return (
    <ScrollView style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(ROUTES_KEY)} />

      <View style={{ padding: 16, gap: 8 }}>
        <Text style={{ fontSize: 18, fontWeight: '600' }}>Routes</Text>
        {(routes?.results ?? []).map((route) => (
          <Pressable
            key={route.id}
            onPress={() => {
              setRouteId(route.id);
              setScheduleId(null);
            }}
            style={{
              padding: 12,
              borderRadius: 8,
              backgroundColor: routeId === route.id ? '#dbeafe' : '#f3f4f6',
            }}
          >
            <Text>{route.name}</Text>
            <Text style={{ color: '#6b7280', fontSize: 12 }}>
              {route.start_point} → {route.end_point}
            </Text>
          </Pressable>
        ))}
      </View>

      {routeId ? (
        <View style={{ padding: 16, gap: 8 }}>
          <Text style={{ fontSize: 18, fontWeight: '600' }}>Departures</Text>
          {(seats?.schedules ?? []).map((schedule) => (
            <Pressable
              key={schedule.id}
              onPress={() => setScheduleId(schedule.id)}
              style={{
                padding: 12,
                borderRadius: 8,
                backgroundColor: scheduleId === schedule.id ? '#dbeafe' : '#f3f4f6',
              }}
            >
              <Text>
                Bus {schedule.bus_no} · {new Date(schedule.departure_time).toLocaleTimeString()}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {scheduleId ? (
        <View style={{ padding: 16, flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {Array.from({ length: SEAT_COUNT }, (_, i) => i + 1).map((seat) => (
            <Pressable
              key={seat}
              disabled={taken.has(seat) || book.isPending}
              onPress={() =>
                book.mutate(seat, {
                  onError: (e) => Alert.alert('Booking failed', (e as Error).message),
                })
              }
              style={{
                width: 44,
                height: 44,
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: 6,
                backgroundColor: taken.has(seat) ? '#e5e7eb' : '#bfdbfe',
              }}
            >
              <Text style={{ color: taken.has(seat) ? '#9ca3af' : '#1e3a8a' }}>{seat}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}
```

- [ ] **Step 7: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/transport.test.ts && npx tsc --noEmit`
Expected: 4 tests PASS, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/transport.ts mobile/su-erp-app/src/features/transport/ mobile/su-erp-app/app/\(student\)/transport.tsx mobile/su-erp-app/src/lib/api/__tests__/transport.test.ts
git commit -m "feat(mobile): add transport routes and seat booking"
```

---

## Task 9: Grievance — the first queueable mutation

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/grievance.ts`
- Create: `mobile/su-erp-app/src/features/grievance/useGrievance.ts`
- Create: `mobile/su-erp-app/app/(student)/grievance.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/grievance.test.ts`

**Interfaces:**
- Consumes: `request`, `enqueue` (Phase 1 Task 11), `useConnectivity`, `Ticket`, `Paginated`.
- Produces:
  - `fetchTickets(): Promise<Paginated<Ticket>>`
  - `createTicket(input: { subject: string; description: string }): Promise<Ticket | { queued: true }>` — sends when online, **queues** when offline

- [ ] **Step 1: Write the failing test**

Create `mobile/su-erp-app/src/lib/api/__tests__/grievance.test.ts`:

```ts
import { useConnectivity } from '../../net/connectivity';
import { createTicket, fetchTickets } from '../grievance';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('../../offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('../client');
const { enqueue } = jest.requireMock('../../offline/queue');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('fetchTickets hits the grievance endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });
  await fetchTickets();
  expect(request).toHaveBeenCalledWith('/api/v1/grievance');
});

test('createTicket posts directly when online', async () => {
  request.mockResolvedValue({ id: 't1' });

  await createTicket({ category: 'hostel', description: 'Fan broken in room 12' });

  expect(request).toHaveBeenCalled();
  expect(enqueue).not.toHaveBeenCalled();
});

test('createTicket queues when offline instead of failing', async () => {
  useConnectivity.setState({ online: false });

  const result = await createTicket({
    category: 'hostel',
    description: 'Fan broken in room 12',
  });

  expect(enqueue).toHaveBeenCalledWith(
    '/api/v1/grievance',
    'POST',
    expect.objectContaining({ category: 'hostel' }),
  );
  expect(result).toEqual({ queued: true });
  expect(request).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/grievance.test.ts`
Expected: FAIL — module missing

- [ ] **Step 3: Write the API module**

Create `mobile/su-erp-app/src/lib/api/grievance.ts`:

```ts
import type { Paginated, Ticket } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { request } from './client';

export interface TicketInput {
  category: string;
  description: string;
}

export function fetchTickets(): Promise<Paginated<Ticket>> {
  return request<Paginated<Ticket>>('/api/v1/grievance');
}

/**
 * The one student mutation that queues. Hostel blocks are exactly where
 * complaints get raised and exactly where the signal dies, so a grievance
 * filed offline is held and replayed rather than lost. Unlike a payment,
 * a complaint landing twenty minutes late is harmless.
 */
export async function createTicket(input: TicketInput): Promise<Ticket | { queued: true }> {
  if (!useConnectivity.getState().online) {
    await enqueue('/api/v1/grievance', 'POST', input);
    return { queued: true };
  }

  return request<Ticket>('/api/v1/grievance', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}
```

- [ ] **Step 4: Write the hook**

Create `mobile/su-erp-app/src/features/grievance/useGrievance.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { createTicket, fetchTickets } from '@/lib/api/grievance';

export const TICKETS_KEY = ['grievance', 'tickets'];

export function useTickets() {
  return useQuery({ queryKey: TICKETS_KEY, queryFn: fetchTickets });
}

export function useCreateTicket() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createTicket,
    onSuccess: () => client.invalidateQueries({ queryKey: TICKETS_KEY }),
  });
}
```

- [ ] **Step 5: Write the screen**

Create `mobile/su-erp-app/app/(student)/grievance.tsx`:

```tsx
import { useState } from 'react';
import { Alert, FlatList, Pressable, Text, TextInput, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { TICKETS_KEY, useCreateTicket, useTickets } from '@/features/grievance/useGrievance';
import { cacheAge } from '@/lib/query/persister';

const CATEGORIES = ['hostel', 'academic', 'harassment', 'it', 'ragging'];

export default function GrievanceScreen() {
  const { data } = useTickets();
  const create = useCreateTicket();
  const [category, setCategory] = useState('hostel');
  const [description, setDescription] = useState('');

  function submit() {
    create.mutate(
      { category, description },
      {
        onSuccess: (result) => {
          setDescription('');
          if (result && 'queued' in result) {
            Alert.alert('Saved offline', 'Your complaint will be sent when you reconnect.');
          }
        },
        onError: (e) => Alert.alert('Could not file complaint', (e as Error).message),
      },
    );
  }

  return (
    <View style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(TICKETS_KEY)} />

      <View style={{ padding: 16, gap: 8 }}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {CATEGORIES.map((option) => (
            <Pressable
              key={option}
              onPress={() => setCategory(option)}
              style={{
                paddingVertical: 8,
                paddingHorizontal: 14,
                borderRadius: 999,
                backgroundColor: category === option ? '#dbeafe' : '#f3f4f6',
              }}
            >
              <Text style={{ textTransform: 'capitalize' }}>{option}</Text>
            </Pressable>
          ))}
        </View>
        <TextInput
          placeholder="What is wrong?"
          value={description}
          onChangeText={setDescription}
          multiline
          style={{
            borderWidth: 1,
            borderColor: '#ccc',
            borderRadius: 8,
            padding: 12,
            minHeight: 80,
          }}
        />
        <Pressable
          onPress={submit}
          disabled={!description || create.isPending}
          style={{ backgroundColor: '#1d4ed8', borderRadius: 8, padding: 14, alignItems: 'center' }}
        >
          <Text style={{ color: '#fff', fontWeight: '600' }}>File complaint</Text>
        </Pressable>
      </View>

      <FlatList
        data={data?.results ?? []}
        keyExtractor={(t) => t.id}
        renderItem={({ item }) => (
          <View style={{ padding: 16, borderBottomWidth: 1, borderBottomColor: '#eee' }}>
            <Text style={{ fontWeight: '600', textTransform: 'capitalize' }}>{item.category}</Text>
            <Text style={{ color: '#555' }} numberOfLines={2}>
              {item.description}
            </Text>
            <Text style={{ color: '#666' }}>
              {item.status}
              {item.urgency ? ` · ${item.urgency}` : ''}
            </Text>
          </View>
        )}
      />
    </View>
  );
}
```

- [ ] **Step 6: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/grievance.test.ts && npx tsc --noEmit`
Expected: 3 tests PASS, no type errors

- [ ] **Step 7: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/grievance.ts mobile/su-erp-app/src/features/grievance/ mobile/su-erp-app/app/\(student\)/grievance.tsx mobile/su-erp-app/src/lib/api/__tests__/grievance.test.ts
git commit -m "feat(mobile): add grievance filing with offline queueing"
```

---

## Task 10: Student home, tab shell, and profile

**Files:**
- Modify: `mobile/su-erp-app/app/(student)/_layout.tsx`
- Modify: `mobile/su-erp-app/app/(student)/index.tsx`
- Create: `mobile/su-erp-app/app/(student)/profile.tsx`
- Create: `mobile/su-erp-app/src/features/home/__tests__/home.test.tsx`

**Interfaces:**
- Consumes: every hook from Tasks 4–9, plus `listDevices`/`revokeDevice` (Phase 1 Task 10).
- Produces: a tab navigator over `index`, `hostel`, `fees`, `canteen`, `transport`, `grievance`, `notifications`, `profile`.

- [ ] **Step 1: Install the tabs dependency**

Run: `cd mobile/su-erp-app && npx expo install @expo/vector-icons`

- [ ] **Step 2: Write the failing test**

Create `mobile/su-erp-app/src/features/home/__tests__/home.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react-native';

import StudentHome from '../../../../app/(student)/index';

jest.mock('@/features/fees/useInvoices', () => ({
  INVOICES_KEY: ['finance', 'invoices'],
  useInvoices: () => ({
    data: { results: [{ id: 'i1', amount: '1500.00', status: 'pending', purpose: 'Hostel' }] },
  }),
}));
jest.mock('@/features/notifications/useInbox', () => ({
  INBOX_KEY: ['notify', 'inbox'],
  useInbox: () => ({ data: { results: [{ id: 'n1', read: false, title: 'Hi', body: '' }] } }),
}));
jest.mock('@/features/hostel/useHostel', () => ({
  ALLOCATIONS_KEY: ['hostel', 'allocations'],
  useMyAllocation: () => ({ data: { results: [] } }),
}));
jest.mock('@/lib/query/persister', () => ({ cacheAge: () => undefined }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

function renderHome() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <StudentHome />
    </QueryClientProvider>,
  );
}

test('home shows the pending dues total', () => {
  renderHome();
  expect(screen.getByText(/1500\.00/)).toBeTruthy();
});

test('home shows the unread notification count', () => {
  renderHome();
  expect(screen.getByText(/1 unread/)).toBeTruthy();
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/features/home`
Expected: FAIL — the current `(student)/index.tsx` renders only the role name

- [ ] **Step 4: Write the tab layout**

Replace `mobile/su-erp-app/app/(student)/_layout.tsx`:

```tsx
import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';

export default function StudentLayout() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: '#1d4ed8' }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarIcon: ({ color, size }) => <Ionicons name="home" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="hostel"
        options={{
          title: 'Hostel',
          tabBarIcon: ({ color, size }) => <Ionicons name="bed" color={color} size={size} />,
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
        name="transport"
        options={{
          title: 'Bus',
          tabBarIcon: ({ color, size }) => <Ionicons name="bus" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="grievance"
        options={{
          title: 'Help',
          tabBarIcon: ({ color, size }) => <Ionicons name="alert-circle" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="notifications"
        options={{
          title: 'Alerts',
          tabBarIcon: ({ color, size }) => <Ionicons name="notifications" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          tabBarIcon: ({ color, size }) => <Ionicons name="person" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
```

- [ ] **Step 5: Write the home screen**

Replace `mobile/su-erp-app/app/(student)/index.tsx`:

```tsx
import { ScrollView, Text, View } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { INVOICES_KEY, useInvoices } from '@/features/fees/useInvoices';
import { useMyAllocation } from '@/features/hostel/useHostel';
import { useInbox } from '@/features/notifications/useInbox';
import { cacheAge } from '@/lib/query/persister';

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View
      style={{
        padding: 16,
        margin: 12,
        marginBottom: 0,
        borderRadius: 12,
        backgroundColor: '#f9fafb',
        gap: 6,
      }}
    >
      <Text style={{ fontSize: 13, color: '#6b7280', textTransform: 'uppercase' }}>{title}</Text>
      {children}
    </View>
  );
}

export default function StudentHome() {
  const { data: invoices } = useInvoices();
  const { data: inbox } = useInbox();
  const { data: allocations } = useMyAllocation();

  const dues = (invoices?.results ?? [])
    .filter((i) => i.status === 'pending')
    .reduce((sum, i) => sum + Number(i.amount), 0);
  const unread = (inbox?.results ?? []).filter((n) => !n.read).length;
  const room = (allocations?.results ?? []).find((a) => a.status === 'confirmed');

  return (
    <ScrollView style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(INVOICES_KEY)} />

      <Card title="Pending dues">
        <Money value={dues.toFixed(2)} style={{ fontSize: 24, fontWeight: '600' }} />
      </Card>

      <Card title="Notifications">
        <Text style={{ fontSize: 18 }}>{unread} unread</Text>
      </Card>

      <Card title="My room">
        <Text style={{ fontSize: 18 }}>{room ? `Room ${room.room}` : 'Not allocated'}</Text>
      </Card>
    </ScrollView>
  );
}
```

- [ ] **Step 6: Write the profile screen**

Create `mobile/su-erp-app/app/(student)/profile.tsx`:

```tsx
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Pressable, ScrollView, Text, View } from 'react-native';

import { listDevices, revokeDevice } from '@/lib/api/auth';
import { useSession } from '@/lib/auth/session';

const DEVICES_KEY = ['auth', 'devices'];

export default function ProfileScreen() {
  const user = useSession((s) => s.user);
  const signOut = useSession((s) => s.signOut);
  const client = useQueryClient();
  const { data: devices } = useQuery({ queryKey: DEVICES_KEY, queryFn: listDevices });

  async function revoke(deviceId: string) {
    await revokeDevice(deviceId);
    await client.invalidateQueries({ queryKey: DEVICES_KEY });
    Alert.alert('Signed out', 'That device has been signed out.');
  }

  return (
    <ScrollView style={{ flex: 1 }}>
      <View style={{ padding: 16, gap: 4 }}>
        <Text style={{ fontSize: 20, fontWeight: '600' }}>{user?.email}</Text>
        <Text style={{ color: '#6b7280' }}>{user?.user_code}</Text>
      </View>

      <View style={{ padding: 16, gap: 12 }}>
        <Text style={{ fontSize: 16, fontWeight: '600' }}>Signed-in devices</Text>
        {(devices ?? []).map((device) => (
          <View
            key={device.device_id}
            style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}
          >
            <View style={{ flex: 1 }}>
              <Text>{device.model_name || device.platform}</Text>
              <Text style={{ color: '#6b7280', fontSize: 12 }}>
                Last seen {new Date(device.last_seen_at).toLocaleString()}
              </Text>
            </View>
            <Pressable onPress={() => void revoke(device.device_id)}>
              <Text style={{ color: '#b00020' }}>Sign out</Text>
            </Pressable>
          </View>
        ))}
      </View>

      <Pressable onPress={() => void signOut()} style={{ padding: 16 }}>
        <Text style={{ color: '#b00020', fontWeight: '600' }}>Sign out of this device</Text>
      </Pressable>
    </ScrollView>
  );
}
```

- [ ] **Step 7: Run the whole suite and typecheck**

Run: `cd mobile/su-erp-app && npx jest && npx tsc --noEmit`
Expected: every test PASSES including the 2 new home tests, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/app/\(student\)/ mobile/su-erp-app/src/features/home/
git commit -m "feat(mobile): add student home dashboard, tab shell, and profile"
```

---

## Task 11: End-to-end verification of the student surface

**Files:**
- Modify: `docs/RUNBOOK-mobile.md`

- [ ] **Step 1: Bring up the services this phase needs**

Run:
```bash
docker compose -f infra/docker-compose.yml up -d postgres redis rabbitmq \
  auth-service hostel-service finance-service canteen-service \
  transport-service grievance-service notification-service gateway
```
Expected: all containers healthy. This is the `default` profile set — do not start the observability profile alongside it (see the local CPU note in the spec).

- [ ] **Step 2: Walk the student flow on a device**

Run `npx expo start` and, signed in as a student, confirm each of:
- home shows dues, unread count, and room
- fees lists invoices and a payment succeeds after the biometric prompt
- canteen accepts a cart and the order appears with status `placed`
- transport shows routes and a seat books
- grievance files a ticket and it appears in the list
- notifications lists the inbox and tapping marks one read

- [ ] **Step 3: Verify offline behavior**

With the app open, enable airplane mode, then:
- confirm the offline banner appears with a timestamp
- confirm each screen still renders its cached data
- file a grievance — confirm the "Saved offline" alert
- attempt a fee payment — confirm it fails with the offline message rather than queueing
- disable airplane mode and confirm the queued grievance appears in the list within a few seconds

- [ ] **Step 4: Record the results**

Append a "Phase 2 — student surface" section to `docs/RUNBOOK-mobile.md` listing the compose command from Step 1 and the offline checks from Step 3 with their observed outcomes.

- [ ] **Step 5: Commit**

```bash
git add docs/RUNBOOK-mobile.md
git commit -m "docs: record verified student surface and offline behavior"
```

---

## Out of scope for Phase 2

- Warden, driver, and canteen-owner surfaces — **Phase 3**
- QR passes, geofenced attendance, live bus tracking, camera grievance, widgets, document vault — **Phase 4**
- Push notifications — the `push-channel` consumer in `notification-service`
- Grievance comment threads and media attachments (media arrives with the camera work in Phase 4)
