export interface VisitorLog {
  id: string;
  visitor_name: string;
  visiting_user_code: string;
  purpose: string;
  phone: string;
  logged_by: string;
  checked_in_at: string;
  checked_out_at: string | null;
}

export interface VisitorInput {
  visitor_name: string;
  visiting_user_code: string;
  purpose?: string;
  phone?: string;
}
