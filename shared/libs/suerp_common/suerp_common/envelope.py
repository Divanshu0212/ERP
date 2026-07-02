"""Uniform API response envelope, exception handler, and pagination.

Every endpoint across every service returns::

    {"success": bool, "data": any, "message": str, "errors": any}

so the frontend can unwrap responses identically regardless of service.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def ok(data=None, message: str = "", status: int = 200) -> Response:
    return Response(
        {"success": True, "data": data, "message": message, "errors": None},
        status=status,
    )


def fail(message: str, errors=None, status: int = 400) -> Response:
    return Response(
        {"success": False, "data": None, "message": message, "errors": errors},
        status=status,
    )


def exception_handler(exc, context):
    """Wrap DRF's default handler output in the standard envelope."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    message = "Request failed"
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
        errors = None
    else:
        errors = detail

    response.data = {
        "success": False,
        "data": None,
        "message": message,
        "errors": errors,
    }
    return response


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return ok(
            {
                "results": data,
                "count": self.page.paginator.count,
                "page": self.page.number,
                "num_pages": self.page.paginator.num_pages,
            }
        )
