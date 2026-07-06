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

import openpyxl
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404
from hostel.lookups import LookupFailed, resolve_user_by_email
from hostel.models import Allocation, AllocationImportBatch, AllocationImportRow, Block, Room
from hostel.serializers import (
    AllocateRequestSerializer,
    AllocationImportBatchDetailSerializer,
    AllocationImportBatchSerializer,
    AllocationSerializer,
    BlockCreateSerializer,
    BlockSerializer,
    RoomCreateSerializer,
    RoomSerializer,
)
from hostel.services import RoomFullError, create_allocation
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
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
            warden = resolve_user_by_email(
                serializer.validated_data["warden_email"], request.META.get("HTTP_AUTHORIZATION")
            )
        except LookupFailed as exc:
            return fail(str(exc), status=400 if exc.reason == "not_found" else 502)

        block = Block.objects.create(
            tenant_id=get_current_tenant(),
            name=serializer.validated_data["name"],
            gender_type=serializer.validated_data["gender_type"],
            warden_id=warden["id"],
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


class AllocationListView(ListAPIView):
    """GET /api/v1/hostel/allocations — tenant-scoped, paginated."""

    serializer_class = AllocationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Allocation.objects.all().order_by("-created_at")


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
        student_email = serializer.validated_data["student_email"]

        try:
            student = resolve_user_by_email(student_email, request.META.get("HTTP_AUTHORIZATION"))
        except LookupFailed as exc:
            return fail(str(exc), status=400 if exc.reason == "not_found" else 502)

        try:
            allocation = create_allocation(room_id, student["id"], get_current_tenant())
        except RoomFullError:
            return fail("Room at full capacity.", status=400)

        return ok(
            AllocationSerializer(allocation).data,
            message="Allocation created.",
            status=201,
        )


ALLOWED_EXTENSIONS = {"csv", "xlsx"}


def _parse_rows(upload, extension) -> list[tuple[str, str]]:
    """Parse an uploaded CSV/XLSX into a list of (room_id, student_email) tuples.

    Expects a header row with columns ``room_id`` and ``student_email`` (any
    order, case-insensitive). Raises ValueError with a caller-facing message
    on missing/misnamed columns or an empty sheet.
    """
    if extension == "csv":
        text = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        if "room_id" not in fieldnames or "student_email" not in fieldnames:
            raise ValueError("CSV must have room_id and student_email columns.")
        rows = []
        for record in reader:
            normalized = {k.strip().lower(): v for k, v in record.items() if k}
            rows.append(
                (
                    (normalized.get("room_id") or "").strip(),
                    (normalized.get("student_email") or "").strip(),
                )
            )
        return rows

    workbook = openpyxl.load_workbook(upload, read_only=True, data_only=True)
    sheet = workbook.active
    sheet_rows = list(sheet.iter_rows(values_only=True))
    if not sheet_rows:
        raise ValueError("XLSX file is empty.")
    header = [str(c).strip().lower() if c is not None else "" for c in sheet_rows[0]]
    if "room_id" not in header or "student_email" not in header:
        raise ValueError("XLSX must have room_id and student_email columns.")
    room_idx = header.index("room_id")
    email_idx = header.index("student_email")
    rows = []
    for record in sheet_rows[1:]:
        if record is None or all(c is None for c in record):
            continue
        room_val = record[room_idx] if room_idx < len(record) else None
        email_val = record[email_idx] if email_idx < len(record) else None
        rows.append(
            (
                str(room_val).strip() if room_val is not None else "",
                str(email_val).strip() if email_val is not None else "",
            )
        )
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

        email_cache: dict[str, dict] = {}
        success_count = 0
        fail_count = 0
        skipped_count = 0

        for row_number, (room_id_raw, student_email_raw) in enumerate(rows, start=1):
            error_message = ""
            allocation = None
            row_status = AllocationImportRow.Status.FAILED

            if not room_id_raw or not student_email_raw:
                error_message = "Row skipped: no email provided."
                row_status = AllocationImportRow.Status.SKIPPED
                skipped_count += 1
            else:
                try:
                    if student_email_raw not in email_cache:
                        email_cache[student_email_raw] = resolve_user_by_email(
                            student_email_raw, auth_header
                        )
                    student = email_cache[student_email_raw]

                    room_uuid = uuid_lib.UUID(room_id_raw)
                    allocation = create_allocation(room_uuid, student["id"], tenant_id)
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
                except ValueError as exc:
                    error_message = str(exc)
                    fail_count += 1

            AllocationImportRow.objects.create(
                tenant_id=tenant_id,
                batch=batch,
                row_number=row_number,
                room_id_raw=room_id_raw,
                student_email_raw=student_email_raw,
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
