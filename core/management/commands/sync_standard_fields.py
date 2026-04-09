"""Sync built-in standard field seed data into master tables."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import CheckupFieldMapping, CheckupLibrary, StandardField, StandardFieldAlias
from core.service.standard_field_seed import DEFAULT_STANDARD_FIELD_SEED_PATH, sync_standard_field_seed


class Command(BaseCommand):
    help = "Sync standard fields, aliases, and checkup mappings from JSON seed data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-json",
            dest="from_json",
            default=str(DEFAULT_STANDARD_FIELD_SEED_PATH),
            help="Path to the seed JSON file. Defaults to the built-in seed.",
        )

    def handle(self, *args, **options):
        seed_path = Path(options["from_json"])
        if not seed_path.exists():
            raise CommandError(f"Seed file not found: {seed_path}")

        stats = sync_standard_field_seed(
            standard_field_model=StandardField,
            alias_model=StandardFieldAlias,
            mapping_model=CheckupFieldMapping,
            checkup_model=CheckupLibrary,
            path=seed_path,
        )

        for key in (
            "created_fields",
            "skipped_fields",
            "created_aliases",
            "skipped_aliases",
            "created_mappings",
            "skipped_mappings",
            "missing_checkups",
        ):
            self.stdout.write(f"{key}: {stats[key]}")
