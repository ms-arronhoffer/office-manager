from contextlib import asynccontextmanager
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.config import settings
from app.tasks.scheduler import start_scheduler, stop_scheduler
from app.database import async_session
from app.seeds.wizard_seed import seed_default_wizard_config


APP_VERSION = "1.0.0"
BUILD_SHA = os.environ.get("BUILD_SHA", "dev")
STARTED_AT = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    async with async_session() as db:
        await seed_default_wizard_config(db)
    yield
    stop_scheduler()


app = FastAPI(
    title="SwiftLease API",
    version=APP_VERSION,
    lifespan=lifespan,
)

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
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
    wizard_configs, vendors, imports, email_rules, trash, site_settings,
    ticket_templates, recurring_ticket_rules, notifications, organizations, billing, api_keys,
    webhooks, operating_expenses, vendor_portal, insurance_certificates, ws, work_order_costs,
    space, gl, cam, lifecycle, ap,
    lease_abstract, management_companies, contacts, client_portal,
)
from app.routers.admin import orgs as admin_orgs, users as admin_users, metrics as admin_metrics, billing as admin_billing, audit as admin_audit  # noqa: E402
from app.auth.dependencies import enforce_org_access, require_feature  # noqa: E402
from fastapi import Depends  # noqa: E402

# Shared guard: block suspended / canceled / past-due-expired orgs from the
# primary application data surface. Applied to data routers below. Deliberately
# NOT applied to auth, organizations, or billing so a locked-out org can still
# authenticate, view its org, and fix billing.
_org_guard = [Depends(enforce_org_access)]

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(managers.router, prefix="/api/v1/managers", tags=["Managers"], dependencies=_org_guard)
app.include_router(offices.router, prefix="/api/v1/offices", tags=["Offices"], dependencies=_org_guard)
app.include_router(leases.router, prefix="/api/v1/leases", tags=["Leases"], dependencies=_org_guard)
app.include_router(lease_abstract.router, prefix="/api/v1/leases", tags=["Lease Abstract"], dependencies=_org_guard)
app.include_router(landlords.router, prefix="/api/v1/landlords", tags=["Landlords"], dependencies=_org_guard)
app.include_router(management_companies.router, prefix="/api/v1/management-companies", tags=["Management Companies"], dependencies=_org_guard)
app.include_router(contacts.router, prefix="/api/v1/contacts", tags=["Contacts"], dependencies=_org_guard)
app.include_router(transitions.router, prefix="/api/v1/transitions", tags=["Transitions"], dependencies=[Depends(enforce_org_access), Depends(require_feature("transitions"))])
app.include_router(hq_hvac.router, prefix="/api/v1/hq-hvac", tags=["HQ HVAC"], dependencies=[Depends(enforce_org_access), Depends(require_feature("hvac"))])
app.include_router(hvac_contracts.router, prefix="/api/v1/hvac-contracts", tags=["HVAC Contracts"], dependencies=[Depends(enforce_org_access), Depends(require_feature("hvac"))])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"], dependencies=_org_guard)
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"], dependencies=_org_guard)
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"], dependencies=_org_guard)
app.include_router(attachments.router, prefix="/api/v1", tags=["Attachments"], dependencies=_org_guard)
app.include_router(ticket_categories.router, prefix="/api/v1/ticket-categories", tags=["Ticket Categories"], dependencies=_org_guard)
app.include_router(maintenance_tickets.router, prefix="/api/v1/maintenance-tickets", tags=["Maintenance Tickets"], dependencies=_org_guard)
app.include_router(activity_log.router, prefix="/api/v1/activity-log", tags=["Activity Log"], dependencies=_org_guard)
app.include_router(search.router, prefix="/api/v1/search", tags=["Search"], dependencies=_org_guard)
app.include_router(preferences.router, prefix="/api/v1/users", tags=["Preferences"], dependencies=_org_guard)
app.include_router(wizard_configs.router, prefix="/api/v1/wizard-configs", tags=["Wizard Configs"], dependencies=_org_guard)
app.include_router(vendors.router, prefix="/api/v1/vendors", tags=["Vendors"], dependencies=_org_guard)
app.include_router(imports.router, prefix="/api/v1/imports", tags=["Imports"], dependencies=_org_guard)
app.include_router(email_rules.router, prefix="/api/v1/email-rules", tags=["Email Rules"], dependencies=_org_guard)
app.include_router(trash.router, prefix="/api/v1/admin/trash", tags=["Admin - Trash"], dependencies=_org_guard)
app.include_router(site_settings.router, prefix="/api/v1/site-settings", tags=["Site Settings"], dependencies=_org_guard)
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


app.include_router(admin_orgs.router, prefix="/admin/v1/orgs", tags=["Admin - Orgs"])
app.include_router(admin_users.router, prefix="/admin/v1/users", tags=["Admin - Users"])
app.include_router(admin_metrics.router, prefix="/admin/v1/metrics", tags=["Admin - Metrics"])
app.include_router(admin_billing.router, prefix="/admin/v1/billing", tags=["Admin - Billing"])
app.include_router(admin_audit.router, prefix="/admin/v1/audit", tags=["Admin - Audit"])


@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "build_sha": BUILD_SHA,
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
    }
