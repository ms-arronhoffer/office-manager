"""In-app assistant / search-to-action API (Item 5, phase c).

Parses a plain-English request into a constrained intent via the AI service,
then maps it onto an existing capability:

* ``navigate``/``search`` intents resolve to a deep-link route or a search query
  the client runs immediately (read-only),
* ``create_ticket`` produces a *confirmable proposal* targeting the existing
  typed ``POST /api/v1/maintenance-tickets`` endpoint. The assistant never
  executes mutations itself and never issues raw actions — the real endpoint
  (and its ``require_role``/entitlement guards) remains the single execution
  path. The caller's permissions are reflected here so the UI can hide actions
  the user may not perform.

Gated by the ``ai_assist`` entitlement and degrades gracefully when Gemini is
not configured.
"""

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.routers.ai import _ai_error_response
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.config import settings
from app.services import ai_service

router = APIRouter()

# Navigation destinations → frontend routes (Item 5 phase b deep-links).
_NAV_ROUTES = {
    "offices": "/offices",
    "leases": "/leases",
    "leases_expiring": "/leases?filter=expiring",
    "maintenance_tickets": "/maintenance-tickets",
    "vendors": "/vendors",
    "landlords": "/landlords",
    "transitions": "/transitions",
    "hvac_contracts": "/hvac-contracts",
    "reports": "/reports",
    "saved_reports": "/saved-reports",
}

# Roles permitted to create a maintenance ticket, mirroring the guard on the
# real POST /maintenance-tickets endpoint.
_TICKET_WRITE_ROLES = ("admin", "editor")


def _can_write_ticket(user: User) -> bool:
    return bool(getattr(user, "is_super_admin", False)) or user.role in _TICKET_WRITE_ROLES


def _dispatch(intent: str, params: dict, user: User) -> AssistantResponse:
    """Map a parsed intent onto a route, search query, or confirmable proposal."""
    model = settings.GEMINI_MODEL

    if intent == "navigate":
        route = _NAV_ROUTES.get(params.get("destination", ""))
        if route:
            return AssistantResponse(
                intent=intent,
                action_type="navigate",
                route=route,
                message=f"Opening {params['destination'].replace('_', ' ')}.",
                model=model,
            )
        return AssistantResponse(
            intent="unknown", action_type="none",
            message="I couldn't find that page.", model=model,
        )

    if intent == "search":
        query = params.get("query", "")
        return AssistantResponse(
            intent=intent,
            action_type="search",
            query=query,
            message=f"Searching for “{query}”." if query else "Searching.",
            model=model,
        )

    if intent == "create_ticket":
        permitted = _can_write_ticket(user)
        body = {
            "subject": params.get("subject", ""),
            "priority": params.get("priority", "medium"),
        }
        if params.get("office_number") is not None:
            body["office_number"] = params["office_number"]
        if not permitted:
            return AssistantResponse(
                intent=intent,
                action_type="action",
                permitted=False,
                confirmation_required=True,
                message="You don't have permission to create maintenance tickets.",
                model=model,
            )
        return AssistantResponse(
            intent=intent,
            action_type="action",
            permitted=True,
            confirmation_required=True,
            proposal={
                "method": "POST",
                "endpoint": "/api/v1/maintenance-tickets",
                "body": body,
                "description": (
                    f"Create a {body['priority']}-priority ticket"
                    + (f" for office {body['office_number']}" if "office_number" in body else "")
                    + (f": {body['subject']}" if body["subject"] else "")
                ),
            },
            message="Please review and confirm this action.",
            model=model,
        )

    return AssistantResponse(
        intent="unknown",
        action_type="none",
        message="Sorry, I didn't understand that request.",
        model=model,
    )


@router.post("", response_model=AssistantResponse)
async def assistant(
    payload: AssistantRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        parsed = await ai_service.parse_assistant_intent(payload.prompt)
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)

    return _dispatch(parsed["intent"], parsed["params"], current_user)
