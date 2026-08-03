"""Attendance endpoints: the day roll and geofenced session marking."""

from attendance.models import AttendanceMark, AttendanceRecord, Session
from attendance.rolling_code import CODE_PERIOD_SECONDS, current_code, is_code_valid
from attendance.serializers import (
    AttendanceMarkSerializer,
    AttendanceRecordSerializer,
    MarkRequestSerializer,
    SessionCreateSerializer,
    SessionSerializer,
)
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.permissions import role_required
from suerp_common.tenancy import get_current_tenant


class AttendanceRecordListCreateView(ListCreateAPIView):
    """GET/POST /api/v1/attendance/ — the flat day roll.

    Predates the geofenced flow below and is kept because it is the only way
    to record attendance that did not come from a student's phone: a paper
    roll typed in later, or a mark corrected by hand.
    """

    serializer_class = AttendanceRecordSerializer

    def get_permissions(self):
        # GET: any authenticated user may view. POST: faculty/admin only.
        if self.request.method == "POST":
            return [role_required("faculty", "admin")()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return AttendanceRecord.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)


class SessionCreateView(APIView):
    """POST /api/v1/attendance/sessions — faculty opens a class meeting."""

    permission_classes = [role_required("faculty", "admin")]

    def post(self, request):
        serializer = SessionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid session.", errors=serializer.errors, status=400)

        session = Session.objects.create(
            tenant_id=get_current_tenant(),
            faculty_id=request.user.id,
            **serializer.validated_data,
        )
        return ok(SessionSerializer(session).data, message="Session opened.", status=201)


class SessionCloseView(APIView):
    """POST /api/v1/attendance/sessions/<id>/close — end the meeting."""

    permission_classes = [role_required("faculty", "admin")]

    def post(self, request, pk):
        # ``objects`` is tenant-scoped, so another tenant's session is simply
        # not found — no cross-tenant existence leak.
        try:
            session = Session.objects.get(pk=pk)
        except Session.DoesNotExist:
            return fail("Session not found.", status=404)

        if session.closed_at is not None:
            return fail("Session is already closed.", status=400)

        session.closed_at = timezone.now()
        session.save(update_fields=["closed_at"])
        return ok(SessionSerializer(session).data, message="Session closed.")


class SessionCodeView(APIView):
    """GET /api/v1/attendance/sessions/<id>/code — the code to display."""

    permission_classes = [role_required("faculty", "admin")]

    def get(self, request, pk):
        try:
            session = Session.objects.get(pk=pk)
        except Session.DoesNotExist:
            return fail("Session not found.", status=404)

        return ok({"code": current_code(session.id), "rotates_in": CODE_PERIOD_SECONDS})


class MarkAttendanceView(APIView):
    """POST /api/v1/attendance/sessions/<id>/mark — a student checks in.

    Four gates, in the order that fails cheapest first: the session must be
    open, the device must not be reporting a mocked location, the code must
    be current, and the device must be inside the fence.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = MarkRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid mark request.", errors=serializer.errors, status=400)

        data = serializer.validated_data

        try:
            session = Session.objects.get(pk=pk)
        except Session.DoesNotExist:
            return fail("Session not found.", status=404)

        if not session.is_open:
            return fail("This session is closed.", status=400)

        if data["mock_location"]:
            return fail("Attendance cannot be marked from a mocked location.", status=400)

        if not is_code_valid(session.id, data["code"]):
            return fail("That code has expired. Use the code on screen now.", status=400)

        distance = session.contains(data["lat"], data["lng"])
        if distance is None:
            return fail("You are not in the classroom.", status=400)

        try:
            # Nested atomic block so the uniqueness violation rolls back only
            # this insert. Without it the IntegrityError marks the surrounding
            # transaction broken and the 409 response can no longer query.
            with transaction.atomic():
                mark = AttendanceMark.objects.create(
                    tenant_id=get_current_tenant(),
                    session=session,
                    student_user_code=request.user.id,
                    distance_m=distance,
                    mock_location=False,
                )
        except IntegrityError:
            return fail("You have already marked attendance for this session.", status=409)

        return ok(AttendanceMarkSerializer(mark).data, message="Attendance marked.", status=201)


class AttendanceSummaryView(APIView):
    """GET /api/v1/attendance/summary — the caller's percentage per course.

    ``held`` counts every session the tenant ran for the course, not only the
    ones the student marked, because the denominator is the whole point: a
    student who attended one of two classes needs to see 50%, not 100%.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = request.user.id
        held = (
            Session.objects.values("course_code")
            .annotate(sessions=Count("id"))
            .order_by("course_code")
        )
        attended = {
            row["session__course_code"]: row["marks"]
            for row in AttendanceMark.objects.filter(student_user_code=student)
            .values("session__course_code")
            .annotate(marks=Count("id"))
        }

        summary = []
        for row in held:
            course = row["course_code"]
            present = attended.get(course, 0)
            summary.append(
                {
                    "course_code": course,
                    "held": row["sessions"],
                    "attended": present,
                    "percentage": round(100 * present / row["sessions"], 1),
                }
            )

        return ok(summary)
