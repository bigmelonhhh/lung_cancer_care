"""Send unread chat notifications to watch devices."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from wx.services.chat_notifications import send_chat_unread_notifications


class Command(BaseCommand):
    help = "Send watch notifications for unread chat messages (default: 30s delay)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--delay-seconds",
            type=int,
            default=30,
            help="Unread delay threshold in seconds (default: 30).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Maximum messages to scan per run (default: 200).",
        )

    def handle(self, *args, **options) -> None:
        delay_seconds = options.get("delay_seconds", 30)
        limit = options.get("limit", 200)
        sent = send_chat_unread_notifications(
            delay_seconds=delay_seconds,
            limit=limit,
        )
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} unread chat notification(s)."))
