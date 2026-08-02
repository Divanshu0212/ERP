/** transport/serializers.py RouteSerializer. */
export interface Route {
  id: string;
  name: string;
  start_point: string;
  end_point: string;
  created_at: string;
}

export type BookingStatus = 'booked' | 'cancelled';

/** transport/serializers.py BookingSerializer. */
export interface Booking {
  id: string;
  schedule_id: string;
  student_user_code: string;
  /** The backend field is seat_no, not seat_number — see transport/models.py. */
  seat_no: number;
  status: BookingStatus;
  created_at: string;
}

/** The compact route summary nested inside a schedule. */
export interface RouteSummary {
  id: string;
  name: string;
  start_point: string;
  end_point: string;
}

/** transport/serializers.py BusScheduleSerializer. */
export interface BusSchedule {
  id: string;
  route: RouteSummary;
  bus_no: string;
  driver_id: string;
  departure_time: string;
  capacity: number;
  booked_count: number;
}

/** transport/serializers.py BookingRequestSerializer. */
export interface BookingInput {
  schedule_id: string;
  seat_no: number;
  idempotency_key?: string;
}
