/** Mirrors Ticket.Status in grievance/models.py — there is no 'closed'. */
export type TicketStatus = 'open' | 'escalated' | 'in_progress' | 'resolved';
export type Urgency = 'low' | 'medium' | 'high' | 'critical';

/** Categories are free-form at the DB level; these are the seeded labels. */
export type TicketCategory = 'hostel' | 'academic' | 'harassment' | 'it' | 'ragging';

/** grievance/serializers.py TicketSerializer. */
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

export interface TicketInput {
  category: string;
  description: string;
}
