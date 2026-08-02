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
