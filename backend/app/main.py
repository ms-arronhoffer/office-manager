from contextlib import asynccontextmanager
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.config import settings
from app.tasks.scheduler import start_scheduler, stop_scheduler, scheduler
from app.database import async_session
from app.utils.rate_limit import org_limiter
from app.utils.logging_config import configure_logging, init_sentry


APP_VERSION = "1.0.0"
BUILD_SHA = os.environ.get("BUILD_SHA", "dev")
STARTED_AT = datetime.now(timezone.utc)

configure_logging()
init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Portfolio Desk API",
    version=APP_VERSION,
    lifespan=lifespan,
)

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.state.org_limiter = org_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

_cors_origins = [settings.FRONTEND_URL]
if settings.ADMIN_FRONTEND_URL:
    _cors_origins.append(settings.ADMIN_FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import (  # noqa: E402
    auth, offices, leases, landlords, transitions,
    hq_hvac, hvac_contracts, reports, dashboard, users, managers, attachments,
    ticket_categories, maintenance_tickets, activity_log, search, preferences,
    vendors, imports, email_rules, trash, site_settings,
    ticket_templates, recurring_ticket_rules, notifications, organizations, billing, api_keys,
    webhooks, operating_expenses, vendor_portal, insurance_certificates, ws, work_order_costs,
    space, gl, cam, lifecycle, ap, ar, financials,
    bank, tax, budgets, inspections,
    lease_abstract, management_companies, contacts, client_portal,
    ai, waivers, document_search, maintenance, saved_reports, assistant,
    support_requests, leasing, resident_portal, announcements, rent,
    leasing_funnel, listings, owners, owner_portal, lease_templates,
    application_templates, buildium, self_storage,
)
from app.routers.admin import orgs as admin_orgs, users as admin_users, metrics as admin_metrics, billing as admin_billing, audit as admin_audit, usage as admin_usage, support_requests as admin_support_requests  # noqa: E402
from app.auth.dependencies import enforce_org_access, require_feature, require_category  # noqa: E402
from fastapi import Depends  # noqa: E402

# Shared guard: block suspended / canceled / past-due-expired orgs from the
# primary application data surface. Applied to data routers below. Deliberately
# NOT applied to auth, organizations, or billing so a locked-out org can still
# authenticate, view its org, and fix billing.
_org_guard = [Depends(enforce_org_access)]

# Primary-category guards (see app.services.categories). Gate only the
# *dedicated* surfaces of each category. Shared property infrastructure
# (offices, space, maintenance, inspections, finance) is intentionally left
# ungated because it is reused across all categories — notably, self storage
# reuses Office as its facility, so gating the offices router on "commercial"
# would break storage.
_commercial_guard = _org_guard + [Depends(require_category("commercial"))]
_residential_guard = _org_guard + [Depends(require_category("residential"))]
_self_storage_guard = _org_guard + [Depends(require_category("self_storage"))]

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(managers.router, prefix="/api/v1/managers", tags=["Managers"], dependencies=_org_guard)
app.include_router(offices.router, prefix="/api/v1/offices", tags=["Offices"], dependencies=_org_guard)
app.include_router(leases.router, prefix="/api/v1/leases", tags=["Leases"], dependencies=_commercial_guard)
app.include_router(document_search.router, prefix="/api/v1/leases", tags=["Lease Document Search"], dependencies=_commercial_guard)
app.include_router(lease_abstract.router, prefix="/api/v1/leases", tags=["Lease Abstract"], dependencies=_commercial_guard)
app.include_router(landlords.router, prefix="/api/v1/landlords", tags=["Landlords"], dependencies=_commercial_guard)
app.include_router(management_companies.router, prefix="/api/v1/management-companies", tags=["Management Companies"], dependencies=_commercial_guard)
app.include_router(contacts.router, prefix="/api/v1/contacts", tags=["Contacts"], dependencies=_org_guard)
app.include_router(transitions.router, prefix="/api/v1/transitions", tags=["Transitions"], dependencies=[Depends(enforce_org_access), Depends(require_feature("transitions"))])
app.include_router(hq_hvac.router, prefix="/api/v1/hq-hvac", tags=["HQ HVAC"], dependencies=[Depends(enforce_org_access), Depends(require_feature("hvac"))])
app.include_router(hvac_contracts.router, prefix="/api/v1/hvac-contracts", tags=["HVAC Contracts"], dependencies=[Depends(enforce_org_access), Depends(require_feature("hvac"))])
app.include_router(maintenance.router, prefix="/api/v1/maintenance", tags=["Maintenance"], dependencies=[Depends(enforce_org_access), Depends(require_feature("maintenance"))])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"], dependencies=_org_guard)
app.include_router(saved_reports.router, prefix="/api/v1/saved-reports", tags=["Saved Reports"], dependencies=_org_guard)
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"], dependencies=_org_guard)
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"], dependencies=_org_guard)
app.include_router(attachments.router, prefix="/api/v1", tags=["Attachments"], dependencies=_org_guard)
app.include_router(ticket_categories.router, prefix="/api/v1/ticket-categories", tags=["Ticket Categories"], dependencies=_org_guard)
app.include_router(maintenance_tickets.router, prefix="/api/v1/maintenance-tickets", tags=["Maintenance Tickets"], dependencies=_org_guard)
app.include_router(activity_log.router, prefix="/api/v1/activity-log", tags=["Activity Log"], dependencies=_org_guard)
app.include_router(search.router, prefix="/api/v1/search", tags=["Search"], dependencies=_org_guard)
app.include_router(assistant.router, prefix="/api/v1/assistant", tags=["Assistant"], dependencies=[Depends(enforce_org_access), Depends(require_feature("ai_assist"))])
app.include_router(preferences.router, prefix="/api/v1/users", tags=["Preferences"], dependencies=_org_guard)
app.include_router(vendors.router, prefix="/api/v1/vendors", tags=["Vendors"], dependencies=_org_guard)
app.include_router(imports.router, prefix="/api/v1/imports", tags=["Imports"], dependencies=_org_guard)
app.include_router(email_rules.router, prefix="/api/v1/email-rules", tags=["Email Rules"], dependencies=_org_guard)
app.include_router(email_rules.public_router, prefix="/api/v1/email-rules", tags=["Email Rules"])
app.include_router(trash.router, prefix="/api/v1/admin/trash", tags=["Admin - Trash"], dependencies=_org_guard)
app.include_router(site_settings.router, prefix="/api/v1/site-settings", tags=["Site Settings"], dependencies=_org_guard)
app.include_router(support_requests.router, prefix="/api/v1/support-requests", tags=["Support Requests"], dependencies=_org_guard)
app.include_router(ticket_templates.router, prefix="/api/v1/ticket-templates", tags=["Ticket Templates"], dependencies=_org_guard)
app.include_router(recurring_ticket_rules.router, prefix="/api/v1/recurring-ticket-rules", tags=["Recurring Ticket Rules"], dependencies=_org_guard)
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"], dependencies=_org_guard)
app.include_router(organizations.router, prefix="/api/v1/organizations", tags=["Organizations"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["API Keys"], dependencies=[Depends(enforce_org_access), Depends(require_feature("api_access"))])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"], dependencies=[Depends(enforce_org_access), Depends(require_feature("webhooks"))])
app.include_router(operating_expenses.router, prefix="/api/v1/operating-expenses", tags=["Operating Expenses"], dependencies=_org_guard)
app.include_router(vendor_portal.router, prefix="/api/v1", tags=["Vendor Portal"])
app.include_router(client_portal.router, prefix="/api/v1", tags=["Client Portal"])
app.include_router(insurance_certificates.router, prefix="/api/v1/insurance-certificates", tags=["Insurance Certificates"], dependencies=_org_guard)
app.include_router(ws.router, tags=["WebSocket"])
app.include_router(work_order_costs.router, prefix="/api/v1", tags=["Work Order Costs"], dependencies=_org_guard)
app.include_router(space.router, prefix="/api/v1", tags=["Space Management"], dependencies=_org_guard)
app.include_router(gl.router, prefix="/api/v1/gl", tags=["General Ledger"], dependencies=_org_guard)
app.include_router(cam.router, prefix="/api/v1/cam", tags=["CAM Reconciliation"], dependencies=_org_guard)
app.include_router(lifecycle.router, prefix="/api/v1/lifecycle", tags=["Lease Lifecycle Accounting"], dependencies=_org_guard)
app.include_router(ap.router, prefix="/api/v1/ap", tags=["Accounts Payable"], dependencies=_org_guard)
app.include_router(ar.router, prefix="/api/v1/ar", tags=["Accounts Receivable"], dependencies=_org_guard)
app.include_router(bank.router, prefix="/api/v1/bank", tags=["Bank Reconciliation"], dependencies=_org_guard)
app.include_router(tax.router, prefix="/api/v1/tax", tags=["Tax & 1099"], dependencies=_org_guard)
app.include_router(budgets.router, prefix="/api/v1/budgets", tags=["Budgeting"], dependencies=_org_guard)
app.include_router(inspections.router, prefix="/api/v1/inspections", tags=["Property Inspections"], dependencies=_org_guard)
app.include_router(leasing.router, prefix="/api/v1/leasing", tags=["Leasing (Residents)"], dependencies=_residential_guard)
app.include_router(lease_templates.router, prefix="/api/v1/lease-templates", tags=["Lease Templates"], dependencies=_residential_guard)
app.include_router(application_templates.router, prefix="/api/v1/application-templates", tags=["Application Templates"], dependencies=_residential_guard)
app.include_router(buildium.router, prefix="/api/v1/buildium", tags=["Buildium Migration"], dependencies=_org_guard)
app.include_router(self_storage.router, prefix="/api/v1/self-storage", tags=["Self Storage"], dependencies=_self_storage_guard)
app.include_router(announcements.router, prefix="/api/v1/announcements", tags=["Resident Announcements"], dependencies=_residential_guard)
app.include_router(rent.router, prefix="/api/v1/rent", tags=["Rent Collection"], dependencies=_residential_guard)
app.include_router(leasing_funnel.router, prefix="/api/v1/leasing-funnel", tags=["Leasing Funnel"], dependencies=_residential_guard)
app.include_router(leasing_funnel.public_router, prefix="/api/v1/leasing-funnel", tags=["Leasing Funnel (Public)"])
app.include_router(listings.router, prefix="/api/v1/listings", tags=["Vacancy Listings"], dependencies=_residential_guard)
app.include_router(listings.public_router, prefix="/api/v1/listings", tags=["Vacancy Listings (Public)"])
app.include_router(resident_portal.router, prefix="/api/v1", tags=["Resident Portal"])
app.include_router(owners.trust_router, prefix="/api/v1/owners/trust-accounts", tags=["Owner Trust Accounts"], dependencies=_residential_guard)
app.include_router(owners.router, prefix="/api/v1/owners", tags=["Owner Accounting"], dependencies=_residential_guard)
app.include_router(owner_portal.router, prefix="/api/v1", tags=["Owner Portal"])
app.include_router(financials.router, prefix="/api/v1/financials", tags=["Financial Statements"], dependencies=_org_guard)
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI Assist"], dependencies=[Depends(enforce_org_access), Depends(ai.reset_ai_usage)])
app.include_router(
    waivers.router,
    prefix="/api/v1/waivers",
    tags=["Digital Waivers"],
    dependencies=[Depends(enforce_org_access), Depends(require_feature("digital_waivers"))],
)
app.include_router(waivers.public_router, prefix="/api/v1/waivers", tags=["Digital Waivers"])


app.include_router(admin_orgs.router, prefix="/admin/v1/orgs", tags=["Admin - Orgs"])
app.include_router(admin_users.router, prefix="/admin/v1/users", tags=["Admin - Users"])
app.include_router(admin_metrics.router, prefix="/admin/v1/metrics", tags=["Admin - Metrics"])
app.include_router(admin_billing.router, prefix="/admin/v1/billing", tags=["Admin - Billing"])
app.include_router(admin_audit.router, prefix="/admin/v1/audit", tags=["Admin - Audit"])
app.include_router(admin_usage.router, prefix="/admin/v1/usage", tags=["Admin - Usage"])
app.include_router(admin_support_requests.router, prefix="/admin/v1/support-requests", tags=["Admin - Support Requests"])


@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "build_sha": BUILD_SHA,
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
    }


@app.get("/api/v1/readyz")
async def readyz():
    """Readiness probe: verifies the app can serve traffic.

    Unlike ``/health`` (liveness — "the process is up"), this checks the
    dependencies required to actually handle requests: database connectivity
    and a running background scheduler. Returns HTTP 503 when not ready so
    orchestrators hold traffic until the app is healthy.
    """
    checks: dict[str, str] = {}

    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        checks["database"] = f"error: {exc.__class__.__name__}"

    checks["scheduler"] = "ok" if scheduler.running else "stopped"

    ready = checks["database"] == "ok" and checks["scheduler"] == "ok"
    payload = {"status": "ready" if ready else "not_ready", "checks": checks}
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload
