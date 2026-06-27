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

scheduler = AsyncIOScheduler()


def start_scheduler():
    scheduler.add_job(check_lease_reminders, "cron", hour=7, minute=0, id="lease_reminders")
    scheduler.add_job(check_hvac_reminders, "cron", hour=7, minute=15, id="hvac_reminders")
    scheduler.add_job(check_hq_pm_reminders, "cron", hour=7, minute=30, id="hq_pm_reminders")
    scheduler.add_job(check_maintenance_reminders, "cron", hour=7, minute=35, id="maintenance_reminders")
    scheduler.add_job(send_weekly_summary, "cron", day_of_week="mon", hour=7, minute=45, id="weekly_summary")
    scheduler.add_job(send_ai_briefings, "cron", day_of_week="mon", hour=7, minute=50, id="ai_briefing")
    scheduler.add_job(create_recurring_tickets, "cron", hour=8, minute=0, id="recurring_tickets")
    scheduler.add_job(check_sla_breaches, "cron", hour=8, minute=30, id="sla_escalation")
    scheduler.add_job(check_insurance_expirations, "cron", hour=8, minute=0, id="insurance_expirations")
    scheduler.add_job(retry_failed_webhooks, "interval", minutes=2, id="webhook_retries")
    scheduler.start()
    print("[SCHEDULER] Started with 10 jobs (9 daily/weekly + webhook retry every 2 min)")


def stop_scheduler():
    scheduler.shutdown()
