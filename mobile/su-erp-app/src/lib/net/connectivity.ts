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
 * student who walks out of a basement sees their queued grievance land within
 * a second, with no manual retry.
 */
export function startConnectivityWatch(): () => void {
  return NetInfo.addEventListener((state) => {
    const online = state.isConnected !== false;
    const wasOnline = useConnectivity.getState().online;
    useConnectivity.getState().setOnline(online);

    if (online && !wasOnline) void replay();
  });
}
