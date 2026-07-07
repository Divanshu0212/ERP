"""Provision an institution (tenant) and its first admin user.

This is the ONLY onboarding path for a new institution — there is deliberately
no public signup endpoint. Operators run::

    python manage.py create_institution \\
        --slug demo-univ --name "Demo University" \\
        --admin-email admin@demo.edu --admin-password 'Passw0rd!123'

The institution and its admin are created atomically. The command is
idempotent-ish: an existing institution (matched by slug) is reused rather
than duplicated, and an existing admin email in that tenant is left untouched
with a notice printed.
"""

from accounts.models import Institution, User
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Create an institution (tenant) and its first admin user."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="Unique institution slug.")
        parser.add_argument("--name", required=True, help="Institution display name.")
        parser.add_argument("--admin-email", required=True, help="First admin's email.")
        parser.add_argument("--admin-password", required=True, help="First admin's password.")
        parser.add_argument("--admin-user-code", required=True, help="user_code for the institution's first admin")

    def handle(self, *args, **options):
        slug = options["slug"]
        name = options["name"]
        admin_email = User.objects.normalize_email(options["admin_email"])
        admin_password = options["admin_password"]
        admin_user_code = options["admin_user_code"]

        with transaction.atomic():
            institution, created = Institution.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "is_active": True},
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"Created institution {slug} ({institution.id}).")
                )
            else:
                self.stdout.write(f"Institution {slug} already exists ({institution.id}); reusing.")

            admin = User.objects.filter(tenant=institution, email=admin_email).first()
            if admin is not None:
                self.stdout.write(
                    f"Admin {admin_email} already exists in {slug} ({admin.user_code}); skipping user creation."
                )
            else:
                admin = User.objects.create_user(
                    tenant=institution,
                    email=admin_email,
                    password=admin_password,
                    role=User.Role.ADMIN,
                    user_code=admin_user_code,
                )
                self.stdout.write(self.style.SUCCESS(f"Created admin {admin_email} ({admin.user_code})."))

        self.stdout.write(f"institution_id={institution.id} admin_id={admin.user_code}")
