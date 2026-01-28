"""Generate daily tasks for a specific date.

定时生成每日任务，每天凌晨执行。
"""

from __future__ import annotations

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from core.service.task_scheduler import generate_daily_tasks_for_date
from core.service.tasks import refresh_task_statuses
from patient_alerts.services.behavior_alerts import BehaviorAlertService
from users.services.patient import PatientService


class Command(BaseCommand):
    help = "Generate DailyTask records starting from a given date (default: today)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--date",
            dest="task_date",
            help="Target date in YYYY-MM-DD format. Defaults to today.",
        )
        parser.add_argument(
            "--sync-membership",
            action="store_true",
            help="Sync membership_expire_at based on paid orders (legacy data alignment).",
        )

    def handle(self, *args, **options) -> None:
        task_date = date.today()
        raw_date = options.get("task_date")
        if raw_date:
            try:
                task_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("Invalid --date, expected YYYY-MM-DD.") from exc

        created_count = generate_daily_tasks_for_date(task_date)
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {created_count} daily task(s) for {task_date.isoformat()}."
            )
        )

        refreshed_count = refresh_task_statuses(as_of_date=task_date)
        self.stdout.write(
            self.style.SUCCESS(
                f"Refreshed {refreshed_count} daily task status(es)."
            )
        )

        if options.get("sync_membership"):
            updated_count, cleared_count = PatientService().sync_membership_expire_at()
            self.stdout.write(
                self.style.SUCCESS(
                    "Synced membership_expire_at for "
                    f"{updated_count} patient(s), cleared {cleared_count}."
                )
            )

        alerts = BehaviorAlertService.run()
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {len(alerts)} behavior alert(s)."
            )
        )
