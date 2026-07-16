"""Allocate and listing endpoints (Task 4.8).

``AllocateView`` STARTS the hostel-allocation saga: it reserves a room
(``occupied_count += 1``) and creates a pending ``Allocation`` in the SAME
``transaction.atomic()`` block as the ``hostel.allocation.requested`` outbox
event — the transactional-outbox guarantee (state and event commit or roll
back together; nothing here talks to RabbitMQ directly,
``drain_outbox_task`` relays it later). finance-service's consumer (see
services/finance-service/billing/consumers.py) reacts to this event by
creating a pending hostel-fee invoice.

``select_for_update()`` on the Room row prevents concurrent over-allocation:
two simultaneous allocate calls against the same last-open bed will
serialize on the row lock, so the second one observes the incremented
``occupied_count`` and correctly 400s instead of double-booking.
"""

import csv
import io
import uuid as uuid_lib
from datetime import date

import openpyxl
import requests  # noqa: F401 -- test patch target: hostel.lookups shares this module object
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from hostel.lookups import LookupFailed, resolve_institution_name, resolve_user_by_code
from hostel.models import (
    Allocation,
    AllocationImportBatch,
    AllocationImportRow,
    Block,
    Room,
    RoomRequest,
)
from hostel.serializers import (
    AllocateRequestSerializer,
    AllocationImportBatchDetailSerializer,
    AllocationImportBatchSerializer,
    AllocationSerializer,
    BlockCreateSerializer,
    BlockSerializer,
    RoomCapacityUpdateSerializer,
    RoomCreateSerializer,
    RoomRequestApproveSerializer,
    RoomRequestCreateSerializer,
    RoomRequestRejectSerializer,
    RoomRequestSerializer,
    RoomSerializer,
)
from hostel.services import RoomFullError, StudentAlreadyAllocatedError, create_allocation
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.outbox import publish_event
from suerp_common.permissions import role_required
from suerp_common.tenancy import get_current_tenant


class AvailableRoomsView(ListAPIView):
    """GET /api/v1/hostel/rooms/available — tenant-scoped, paginated."""

    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filter in the DB (not Python) so this scales — ``is_available`` is a
        # computed property, but its condition maps directly to a queryset
        # filter, keeping pagination's LIMIT/OFFSET push-down intact.
        return Room.objects.filter(occupied_count__lt=F("capacity")).order_by("room_no")


class AvailableRoomsTemplateView(APIView):
    """GET /api/v1/hostel/rooms/available-template — CSV download of available
    rooms, pre-filled with room_id/room_name so a warden only has to type in
    student_user_code before re-uploading to /api/v1/hostel/allocate/bulk.

    Returns a raw text/csv HttpResponse, not the JSON envelope — this is a file
    download, not a data API call, same as the frontend's earlier static-asset
    link it replaces.
    """

    permission_classes = [role_required("warden", "admin")]

    def get(self, request):
        from django.http import HttpResponse

        rooms = (
            Room.objects.filter(occupied_count__lt=F("capacity"))
            .select_related("block")
            .order_by("block__name", "room_no")
        )

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["room_id", "room_name", "student_user_code", "fee_structure_id", "due_date"]
        )
        for room in rooms:
            free_seats = room.capacity - room.occupied_count
            room_name = f"{room.block.name} - {room.room_no}"
            for _ in range(free_seats):
                writer.writerow([str(room.id), room_name, "", "", ""])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="allocation-template.csv"'
        return response


class BlockListCreateView(ListCreateAPIView):
    """GET lists blocks (tenant-scoped, paginated); POST creates one.

    Admin-only: this is hostel setup, not a warden's day-to-day workflow.
    """

    permission_classes = [role_required("admin")]

    def get_queryset(self):
        return Block.objects.all().order_by("name")

    def get_serializer_class(self):
        return BlockCreateSerializer if self.request.method == "POST" else BlockSerializer

    def post(self, request):
        serializer = BlockCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid block payload.", errors=serializer.errors, status=400)

        try:
            warden = resolve_user_by_code(
                serializer.validated_data["warden_user_code"],
                request.META.get("HTTP_AUTHORIZATION"),
            )
        except LookupFailed as exc:
            return fail(str(exc), status=400 if exc.reason == "not_found" else 502)

        block = Block.objects.create(
            tenant_id=get_current_tenant(),
            name=serializer.validated_data["name"],
            gender_type=serializer.validated_data["gender_type"],
            warden_id=warden["user_code"],
        )
        return ok(BlockSerializer(block).data, message="Block created.", status=201)


class RoomListCreateView(ListCreateAPIView):
    """GET lists ALL rooms (tenant-scoped, paginated) for management — distinct
    from AvailableRoomsView, which filters to open rooms for the allocation
    picker. POST creates a room; admin or warden may do this."""

    permission_classes = [role_required("admin", "warden")]

    def get_queryset(self):
        return Room.objects.all().order_by("block__name", "room_no")

    def get_serializer_class(self):
        return RoomCreateSerializer if self.request.method == "POST" else RoomSerializer

    def post(self, request):
        serializer = RoomCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid room payload.", errors=serializer.errors, status=400)

        block = get_object_or_404(Block.objects.all(), id=serializer.validated_data["block_id"])
        room = Room.objects.create(
            tenant_id=get_current_tenant(),
            block=block,
            room_no=serializer.validated_data["room_no"],
            capacity=serializer.validated_data["capacity"],
        )
        return ok(RoomSerializer(room).data, message="Room created.", status=201)


class RoomDetailView(APIView):
    """PATCH /api/v1/hostel/rooms/<id> — admin edits room capacity.

    Increasing is always allowed. Decreasing below the room's current
    occupied_count is rejected — a room can never show fewer seats than
    students already living in it.
    """

    permission_classes = [role_required("admin")]

    def patch(self, request, pk):
        serializer = RoomCapacityUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid capacity payload.", errors=serializer.errors, status=400)

        room = get_object_or_404(Room.objects.all(), id=pk)
        new_capacity = serializer.validated_data["capacity"]
        if new_capacity < room.occupied_count:
            return fail(
                f"Capacity cannot be lower than current occupancy ({room.occupied_count}).",
                status=400,
            )

        room.capacity = new_capacity
        room.save(update_fields=["capacity"])
        return ok(RoomSerializer(room).data, message="Room capacity updated.")


class AllocationListView(ListAPIView):
    """GET /api/v1/hostel/allocations — tenant-scoped, paginated."""

    serializer_class = AllocationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Allocation.objects.select_related("room", "room__block").order_by("-created_at")
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs


class ReleaseAllocationView(APIView):
    """POST /api/v1/hostel/allocations/<id>/release — warden manually releases
    an allocation. Same accounting as the automated payment-saga release path
    in hostel/consumers.py (_apply_outcome's FAILED branch): frees the room
    seat under a row lock and emits the same hostel.allocation.released event,
    just triggered directly instead of by a payment-failed/timeout event.
    """

    permission_classes = [role_required("warden", "admin")]

    def post(self, request, pk):
        allocation = get_object_or_404(Allocation.objects.all(), id=pk)
        if allocation.status == Allocation.Status.RELEASED:
            return fail("Allocation is already released.", status=400)

        tenant_id = allocation.tenant_id
        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=allocation.room_id)
            allocation.status = Allocation.Status.RELEASED
            allocation.save(update_fields=["status"])
            room.occupied_count = max(0, room.occupied_count - 1)
            room.save(update_fields=["occupied_count"])
            publish_event(
                "hostel.allocation.released",
                tenant_id=tenant_id,
                payload={
                    "allocation_id": str(allocation.id),
                    "student_user_code": allocation.student_user_code,
                    "room_id": str(allocation.room_id),
                },
            )

        return ok(AllocationSerializer(allocation).data, message="Allocation released.")


class RoomRequestListCreateView(APIView):
    """GET /api/v1/hostel/room-requests?status=pending — warden queue.
    POST /api/v1/hostel/room-requests — student requests a specific room.

    ``status`` query param on GET defaults to ``pending`` (the only queue a
    warden normally works from) but accepts any RoomRequest.Status value.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [role_required("student")()]
        return [role_required("warden", "admin")()]

    def get(self, request):
        status_filter = request.query_params.get("status", RoomRequest.Status.PENDING)
        requests_qs = RoomRequest.objects.filter(status=status_filter).order_by("-requested_on")
        return ok(RoomRequestSerializer(requests_qs, many=True).data)

    def post(self, request):
        serializer = RoomRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid room request payload.", errors=serializer.errors, status=400)

        room = get_object_or_404(Room.objects.all(), id=serializer.validated_data["room_id"])
        if not room.is_available:
            return fail("Room is at full capacity.", status=400)

        try:
            # Savepoint so a constraint violation only rolls back this INSERT,
            # not any surrounding transaction (e.g. Django's test-case atomic).
            with transaction.atomic():
                room_request = RoomRequest.objects.create(
                    tenant_id=get_current_tenant(),
                    student_user_code=request.user.id,
                    room=room,
                    status=RoomRequest.Status.PENDING,
                )
        except IntegrityError:
            # DB-level guard (roomrequest_one_pending_per_student_room): the
            # student already has a pending request for this room. A repeat
            # submit is a no-op, not a second queue entry.
            return fail("You already have a pending request for this room.", status=400)

        return ok(
            RoomRequestSerializer(room_request).data,
            message="Room request submitted.",
            status=201,
        )


class ApproveRoomRequestView(APIView):
    """POST /api/v1/hostel/room-requests/<id>/approve — warden approves.

    Calls create_allocation() unchanged (same lock/capacity-check/atomic-
    commit/outbox path AllocateView uses), passing through the chosen
    fee_structure_id and this tenant's institution name so finance-service's
    consumer can price and label the resulting invoice correctly. Marks the
    RoomRequest approved in the SAME response cycle as create_allocation's own
    atomic block — a RoomRequest left ``pending`` after a successful
    Allocation would be a confusing, permanently-stuck state for the warden UI.
    """

    permission_classes = [role_required("warden", "admin")]

    def post(self, request, pk):
        serializer = RoomRequestApproveSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid approval payload.", errors=serializer.errors, status=400)

        fee_structure_id = serializer.validated_data.get("fee_structure_id")
        due_date = serializer.validated_data.get("due_date")
        if bool(fee_structure_id) != bool(due_date):
            return fail(
                "fee_structure_id and due_date must be given together, or neither.",
                status=400,
            )

        # Fetch by id alone (any status): an unknown id 404s, but an
        # already-decided one must reach the conditional update below so it
        # short-circuits to a clean 400 "already decided" — not a 404.
        room_request = get_object_or_404(RoomRequest.objects.all(), id=pk)

        # Flip pending -> approved FIRST, with an atomic conditional update that
        # only one caller can win (rowcount == 1). A duplicate/replayed approve
        # (or a concurrent one) sees the row already non-pending, so its update
        # affects 0 rows and we short-circuit BEFORE calling create_allocation —
        # this is what prevents a second Allocation + second invoice for the
        # same request. create_allocation only runs if we won the flip.
        university_name = resolve_institution_name(request.META.get("HTTP_AUTHORIZATION"))

        try:
            with transaction.atomic():
                flipped = RoomRequest.objects.filter(
                    id=pk, status=RoomRequest.Status.PENDING
                ).update(
                    status=RoomRequest.Status.APPROVED,
                    decided_on=timezone.now(),
                    decided_by=request.user.id,
                )
                if flipped != 1:
                    return fail("Room request has already been decided.", status=400)

                create_allocation(
                    room_request.room_id,
                    room_request.student_user_code,
                    get_current_tenant(),
                    fee_structure_id=fee_structure_id,
                    university_name=university_name,
                    due_date=due_date,
                )
        except RoomFullError:
            # The flip is rolled back with the surrounding atomic block, so the
            # request stays pending (not stranded as approved-with-no-allocation).
            return fail("Room is no longer available.", status=400)
        except StudentAlreadyAllocatedError as exc:
            return fail(str(exc), status=400)

        room_request.refresh_from_db()
        return ok(RoomRequestSerializer(room_request).data, message="Room request approved.")


class RejectRoomRequestView(APIView):
    """POST /api/v1/hostel/room-requests/<id>/reject — warden rejects."""

    permission_classes = [role_required("warden", "admin")]

    def post(self, request, pk):
        serializer = RoomRequestRejectSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid rejection payload.", errors=serializer.errors, status=400)

        room_request = get_object_or_404(
            RoomRequest.objects.filter(status=RoomRequest.Status.PENDING), id=pk
        )
        room_request.status = RoomRequest.Status.REJECTED
        room_request.decided_on = timezone.now()
        room_request.decided_by = request.user.id
        room_request.rejection_reason = serializer.validated_data["rejection_reason"]
        room_request.save(update_fields=["status", "decided_on", "decided_by", "rejection_reason"])

        return ok(RoomRequestSerializer(room_request).data, message="Room request rejected.")


class MyRoomRequestsView(ListAPIView):
    """GET /api/v1/hostel/room-requests/mine — the caller's own requests."""

    serializer_class = RoomRequestSerializer
    permission_classes = [role_required("student")]

    def get_queryset(self):
        return RoomRequest.objects.filter(student_user_code=self.request.user.id).order_by(
            "-requested_on"
        )


class AllocationImportLogListView(ListAPIView):
    """GET /api/v1/hostel/allocations/import-logs — tenant-scoped, paginated."""

    serializer_class = AllocationImportBatchSerializer
    permission_classes = [role_required("warden", "admin")]

    def get_queryset(self):
        return AllocationImportBatch.objects.all()


class AllocationImportLogDetailView(RetrieveAPIView):
    """GET /api/v1/hostel/allocations/import-logs/<id> — batch + its rows.

    ``get_queryset()`` is overridden (rather than a class-level ``queryset``
    attribute) so the tenant-scoping manager re-evaluates per request. A
    class-level ``AllocationImportBatch.objects.all()`` would be evaluated
    once — whenever ``hostel.views`` is first imported, which happens mid
    request the first time any hostel URL is dispatched — freezing the
    tenant filter to whatever tenant was active at that moment and leaking
    across every later request from a different tenant.
    """

    serializer_class = AllocationImportBatchDetailSerializer
    permission_classes = [role_required("warden", "admin")]

    def get_queryset(self):
        return AllocationImportBatch.objects.all()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return ok(serializer.data)


class AllocateView(APIView):
    permission_classes = [role_required("warden", "admin")]

    def post(self, request):
        serializer = AllocateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid allocation request.", errors=serializer.errors, status=400)

        room_id = serializer.validated_data["room_id"]
        student_user_code = serializer.validated_data["student_user_code"]
        fee_structure_id = serializer.validated_data.get("fee_structure_id")
        due_date = serializer.validated_data.get("due_date")

        if bool(fee_structure_id) != bool(due_date):
            return fail(
                "fee_structure_id and due_date must be given together, or neither.",
                status=400,
            )

        try:
            student = resolve_user_by_code(
                student_user_code, request.META.get("HTTP_AUTHORIZATION")
            )
        except LookupFailed as exc:
            return fail(str(exc), status=400 if exc.reason == "not_found" else 502)

        try:
            allocation = create_allocation(
                room_id,
                student["user_code"],
                get_current_tenant(),
                fee_structure_id=fee_structure_id,
                due_date=due_date,
            )
        except RoomFullError:
            return fail("Room at full capacity.", status=400)
        except StudentAlreadyAllocatedError as exc:
            return fail(str(exc), status=400)

        return ok(
            AllocationSerializer(allocation).data,
            message="Allocation created.",
            status=201,
        )


ALLOWED_EXTENSIONS = {"csv", "xlsx"}


def _parse_due_date_or_none(raw: str):
    """Parse a CSV/XLSX due_date cell (expected YYYY-MM-DD). Returns None if
    unparseable, so the caller can distinguish "bad format" from "in the
    past" with one parse instead of two."""
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_rows(upload, extension) -> list[tuple[str, str, str, str]]:
    """Parse an uploaded CSV/XLSX into a list of
    (room_id, student_user_code, fee_structure_id_raw, due_date_raw) tuples.

    Expects a header row with columns room_id, student_user_code,
    fee_structure_id, due_date (any order, case-insensitive).
    fee_structure_id/due_date may be blank per row.
    """
    columns = ("room_id", "student_user_code", "fee_structure_id", "due_date")

    if extension == "csv":
        text = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        if "room_id" not in fieldnames or "student_user_code" not in fieldnames:
            raise ValueError("CSV must have room_id and student_user_code columns.")
        rows = []
        for record in reader:
            normalized = {k.strip().lower(): v for k, v in record.items() if k}
            rows.append(tuple((normalized.get(col) or "").strip() for col in columns))
        return rows

    workbook = openpyxl.load_workbook(upload, read_only=True, data_only=True)
    sheet = workbook.active
    sheet_rows = list(sheet.iter_rows(values_only=True))
    if not sheet_rows:
        raise ValueError("XLSX file is empty.")
    header = [str(c).strip().lower() if c is not None else "" for c in sheet_rows[0]]
    if "room_id" not in header or "student_user_code" not in header:
        raise ValueError("XLSX must have room_id and student_user_code columns.")
    col_idx = {col: header.index(col) if col in header else None for col in columns}

    def _cell(record, col):
        idx = col_idx[col]
        if idx is None or idx >= len(record):
            return ""
        value = record[idx]
        return str(value).strip() if value is not None else ""

    rows = []
    for record in sheet_rows[1:]:
        if record is None or all(c is None for c in record):
            continue
        rows.append(tuple(_cell(record, col) for col in columns))
    return rows


class AllocateBulkView(APIView):
    """POST /api/v1/hostel/allocate/bulk — CSV/XLSX bulk allocation.

    Runs synchronously within the request (no async worker/queue — see the
    design spec for why this matches the expected load). Each row is
    resolved and allocated independently; a bad row is recorded as a
    failed AllocationImportRow and processing continues, so the response
    always reports success_count/fail_count out of total_rows rather than
    failing the whole batch.
    """

    permission_classes = [role_required("warden", "admin")]
    parser_classes = [MultiPartParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return fail("No file uploaded.", status=400)

        extension = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        if extension not in ALLOWED_EXTENSIONS:
            return fail("File must be .csv or .xlsx.", status=415)

        try:
            rows = _parse_rows(upload, extension)
        except ValueError as exc:
            return fail(str(exc), status=400)

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        tenant_id = get_current_tenant()

        batch = AllocationImportBatch.objects.create(
            tenant_id=tenant_id,
            uploaded_by=request.user.id,
            filename=upload.name,
            total_rows=len(rows),
        )

        code_cache: dict[str, dict] = {}
        success_count = 0
        fail_count = 0
        skipped_count = 0

        for row_number, (
            room_id_raw,
            student_user_code_raw,
            fee_structure_id_raw,
            due_date_raw,
        ) in enumerate(rows, start=1):
            error_message = ""
            allocation = None
            row_status = AllocationImportRow.Status.FAILED

            parsed_due_date = _parse_due_date_or_none(due_date_raw) if due_date_raw else None

            if not room_id_raw or not student_user_code_raw:
                error_message = "Row skipped: no user_code provided."
                row_status = AllocationImportRow.Status.SKIPPED
                skipped_count += 1
            elif bool(fee_structure_id_raw) != bool(due_date_raw):
                error_message = "fee_structure_id and due_date must be given together, or neither."
                fail_count += 1
            elif due_date_raw and parsed_due_date is None:
                error_message = f"Invalid due_date: {due_date_raw!r} (expected YYYY-MM-DD)."
                fail_count += 1
            elif due_date_raw and parsed_due_date <= timezone.now().date():
                error_message = "due_date must be in the future."
                fail_count += 1
            else:
                try:
                    if student_user_code_raw not in code_cache:
                        code_cache[student_user_code_raw] = resolve_user_by_code(
                            student_user_code_raw, auth_header
                        )
                    student = code_cache[student_user_code_raw]

                    room_uuid = uuid_lib.UUID(room_id_raw)
                    fee_structure_id = (
                        uuid_lib.UUID(fee_structure_id_raw) if fee_structure_id_raw else None
                    )
                    allocation = create_allocation(
                        room_uuid,
                        student["user_code"],
                        tenant_id,
                        fee_structure_id=fee_structure_id,
                        due_date=due_date_raw or None,
                    )
                    row_status = AllocationImportRow.Status.SUCCESS
                    success_count += 1
                except LookupFailed as exc:
                    error_message = str(exc)
                    fail_count += 1
                except Http404:
                    error_message = f"Room {room_id_raw} not found."
                    fail_count += 1
                except RoomFullError as exc:
                    error_message = str(exc)
                    fail_count += 1
                except StudentAlreadyAllocatedError as exc:
                    error_message = str(exc)
                    fail_count += 1
                except ValueError as exc:
                    error_message = str(exc)
                    fail_count += 1

            AllocationImportRow.objects.create(
                tenant_id=tenant_id,
                batch=batch,
                row_number=row_number,
                room_id_raw=room_id_raw,
                student_user_code_raw=student_user_code_raw,
                status=row_status,
                error_message=error_message,
                allocation=allocation,
            )

        batch.success_count = success_count
        batch.fail_count = fail_count
        batch.skipped_count = skipped_count
        batch.save(update_fields=["success_count", "fail_count", "skipped_count"])

        return ok(
            {
                "batch_id": str(batch.id),
                "total_rows": len(rows),
                "success_count": success_count,
                "fail_count": fail_count,
                "skipped_count": skipped_count,
            },
            message="Bulk import processed.",
            status=201,
        )
