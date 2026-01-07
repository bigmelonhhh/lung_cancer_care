"""Refresh treatment cycle status based on end_date."""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand

from core.service.treatment_cycle import refresh_expired_treatment_cycles


class Command(BaseCommand):
    help = "Refresh expired treatment cycles to completed status."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="date",
            default=None,
            help="Optional date in YYYY-MM-DD format.",
        )

    def handle(self, *args, **options):
        raw_date = options.get("date")
        task_date = None
        if raw_date:
            try:
                task_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError("Invalid date format, use YYYY-MM-DD.") from exc

        updated_count = refresh_expired_treatment_cycles(task_date=task_date)
        self.stdout.write(
            self.style.SUCCESS(f"Updated {updated_count} expired treatment cycles.")
        )
