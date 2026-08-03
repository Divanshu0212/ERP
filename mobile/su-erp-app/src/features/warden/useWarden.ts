import type { TicketStatus } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  checkoutVisitor,
  fetchBlockRoster,
  fetchEscalatedTickets,
  fetchVisitors,
  logVisitor,
  setTicketStatus,
} from '@/lib/api/warden';

export const WARDEN_TICKETS_KEY = ['warden', 'tickets'];
export const VISITORS_KEY = ['warden', 'visitors'];
export const ROSTER_KEY = ['warden', 'roster'];

export function useBlockRoster() {
  return useQuery({ queryKey: ROSTER_KEY, queryFn: fetchBlockRoster });
}

export function useWardenTickets() {
  return useQuery({ queryKey: WARDEN_TICKETS_KEY, queryFn: fetchEscalatedTickets });
}

export function useSetTicketStatus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TicketStatus }) =>
      setTicketStatus(id, status),
    onSuccess: () => client.invalidateQueries({ queryKey: WARDEN_TICKETS_KEY }),
  });
}

export function useVisitors() {
  return useQuery({ queryKey: VISITORS_KEY, queryFn: () => fetchVisitors() });
}

export function useLogVisitor() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: logVisitor,
    onSuccess: () => client.invalidateQueries({ queryKey: VISITORS_KEY }),
  });
}

export function useCheckoutVisitor() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: checkoutVisitor,
    onSuccess: () => client.invalidateQueries({ queryKey: VISITORS_KEY }),
  });
}
