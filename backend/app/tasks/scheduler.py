import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.tasks.lease_reminders import check_lease_reminders
from app.tasks.hvac_reminders import check_hvac_reminders, check_hq_pm_reminders
from app.tasks.weekly_summary import send_weekly_summary
from app.tasks.ai_briefing import send_ai_briefings
from app.tasks.recurring_tickets import create_recurring_tickets
from app.tasks.sla_escalation import check_sla_breaches
from app.tasks.webhook_retry import retry_failed_webhooks
from app.tasks.insurance_reminders import check_insurance_expirations
from app.tasks.maintenance_reminders import check_maintenance_reminders
from app.tasks.pm_work_orders import generate_pm_work_orders
from app.tasks.scheduled_reports import send_scheduled_reports
from app.tasks.knowledge_index import reindex_knowledge
from app.tasks.billing_hygiene import run_billing_hygiene
from app.tasks.audit_log_pruning import run_audit_log_pruning
from app.tasks.job_status import run_tracked

logger = logging.getLogger("app.tasks")

scheduler = AsyncIOScheduler()

# (job_id, callable, trigger, trigger_kwargs). Every job is wrapped with
# ``run_tracked`` so it records execution status and is guarded by a Postgres
# advisory lock -- ensuring it runs at most once even across multiple backend
# replicas.
_JOBS = [
    ("lease_reminders", check_lease_reminders, "cron", {"hour": 7, "minute": 0}),
    ("hvac_reminders", check_hvac_reminders, "cron", {"hour": 7, "minute": 15}),
    ("hq_pm_reminders", check_hq_pm_reminders, "cron", {"hour": 7, "minute": 30}),
    ("maintenance_reminders", check_maintenance_reminders, "cron", {"hour": 7, "minute": 35}),
    ("pm_work_orders", generate_pm_work_orders, "cron", {"hour": 6, "minute": 30}),
    ("weekly_summary", send_weekly_summary, "cron", {"day_of_week": "mon", "hour": 7, "minute": 45}),
    ("ai_briefing", send_ai_briefings, "cron", {"day_of_week": "mon", "hour": 7, "minute": 50}),
    ("recurring_tickets", create_recurring_tickets, "cron", {"hour": 8, "minute": 0}),
    ("sla_escalation", check_sla_breaches, "cron", {"hour": 8, "minute": 30}),
    ("insurance_expirations", check_insurance_expirations, "cron", {"hour": 8, "minute": 0}),
    ("scheduled_reports", send_scheduled_reports, "cron", {"hour": 8, "minute": 15}),
    ("webhook_retries", retry_failed_webhooks, "interval", {"minutes": 2}),
    ("knowledge_reindex", reindex_knowledge, "cron", {"hour": 3, "minute": 0}),
    ("billing_hygiene", run_billing_hygiene, "cron", {"hour": 6, "minute": 0}),
    ("audit_log_pruning", run_audit_log_pruning, "cron", {"hour": 2, "minute": 0}),
]


def start_scheduler():
    for job_id, fn, trigger, kwargs in _JOBS:
        scheduler.add_job(run_tracked(job_id, fn), trigger, id=job_id, **kwargs)
    scheduler.start()
    logger.info("Scheduler started", extra={"job_count": len(scheduler.get_jobs())})


def stop_scheduler():
    scheduler.shutdown()
