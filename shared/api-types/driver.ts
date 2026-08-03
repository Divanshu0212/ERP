export interface Trip {
  id: string;
  schedule: string;
  driver_id: string;
  started_at: string;
  ended_at: string | null;
}

export interface BreadcrumbPoint {
  lat: string;
  lng: string;
  recorded_at: string;
}

export interface LivePosition {
  lat: string;
  lng: string;
  recorded_at: string;
  trip_id: string;
}
