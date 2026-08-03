import NetInfo from '@react-native-community/netinfo';
import { create } from 'zustand';

import { setReachabilityHandlers } from '../api/client';
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
 * student who walks out of a basement sees their queued grievance land within
 * a second, with no manual retry.
 */
export function startConnectivityWatch(): () => void {
  setReachabilityHandlers({ onReachable: notifyReachable, onUnreachable: notifyUnreachable });

  return NetInfo.addEventListener((state) => {
    const online = state.isConnected !== false;
    const wasOnline = useConnectivity.getState().online;
    useConnectivity.getState().setOnline(online);

    if (online && !wasOnline) void replay();
  });
}

/** True once a request has failed to reach the server since the last success. */
let sawUnreachable = false;

/**
 * Called by the API client when a request could not reach the server at all.
 *
 * NetInfo cannot see this: the radio is up, so no connectivity event fires and
 * the queue would otherwise sit undrained until an unrelated real network drop
 * happened to occur.
 */
export function notifyUnreachable(): void {
  sawUnreachable = true;
}

/**
 * Called by the API client on any successful response — hard evidence the
 * server is reachable again. If something had previously failed to reach it,
 * this is the moment to drain the queue, because it is the only signal that
 * a radio-up/route-down outage has ended.
 */
export function notifyReachable(): void {
  if (!sawUnreachable) return;
  sawUnreachable = false;
  void replay();
}
