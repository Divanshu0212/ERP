export interface AttendanceSession {
  id: string;
  course_code: string;
  faculty_id: string;
  lat: string;
  lng: string;
  radius_m: number;
  opened_at: string;
  closed_at: string | null;
}

export interface AttendanceMark {
  id: string;
  session: string;
  student_user_code: string;
  distance_m: number;
  mock_location: boolean;
  marked_at: string;
}

export interface CourseSummary {
  course_code: string;
  held: number;
  attended: number;
  percentage: number;
}
