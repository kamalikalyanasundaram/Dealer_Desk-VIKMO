from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import exception_handler


def _validation_details(data):
    if not isinstance(data, dict):
        return []

    details = []
    for field, messages in data.items():
        if field == "detail":
            continue
        if not isinstance(messages, (list, tuple)):
            messages = [messages]
        details.append({"field": str(field), "messages": [str(message) for message in messages]})
    return details


def contract_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return Response(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred.",
                    "details": [],
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if response.status_code == status.HTTP_404_NOT_FOUND:
        code = "NOT_FOUND"
        message = str(response.data.get("detail", "Resource not found."))
        details = []
    elif response.status_code == status.HTTP_400_BAD_REQUEST:
        code = "VALIDATION_ERROR"
        message = "Malformed JSON request." if isinstance(exc, ParseError) else "Invalid request data."
        details = _validation_details(response.data)
    else:
        code = "VALIDATION_ERROR"
        message = str(response.data.get("detail", "Request could not be processed."))
        details = []

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response