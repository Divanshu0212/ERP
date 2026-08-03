/** Mirrors Allocation.Status in hostel/models.py — there is no 'cancelled'. */
export type AllocationStatus = 'pending' | 'confirmed' | 'released';
export type RoomRequestStatus = 'pending' | 'approved' | 'rejected';

/** hostel/serializers.py AllocationSerializer. */
export interface Allocation {
  id: string;
  status: AllocationStatus;
  /** The room's id and display name are flattened onto the allocation. */
  room_id: string;
  room_name: string;
  student_user_code: string;
  allocated_on: string;
}

/** hostel/serializers.py RoomRequestSerializer. */
export interface RoomRequest {
  id: string;
  student_user_code: string;
  room_id: string;
  room_name: string;
  status: RoomRequestStatus;
  requested_on: string;
  decided_on: string | null;
  rejection_reason: string | null;
}

/** RoomRequestCreateSerializer takes the target room, not free-form preferences. */
export interface RoomRequestInput {
  room_id: string;
}

/** hostel/serializers.py RoomSerializer. */
export interface Room {
  id: string;
  block: string;
  block_name: string;
  room_no: string;
  capacity: number;
  occupied_count: number;
  is_available: boolean;
}
