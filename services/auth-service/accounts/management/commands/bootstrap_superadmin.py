"""Bootstrap the first platform superadmin (operator).

A fresh install has no way in: there is no public signup, and institution
onboarding itself is driven by a platform operator. This command creates that
operator. Run::

    python manage.py bootstrap_superadmin \\
        --email super@suerp.io --password 'Str0ngPass!'

It get_or_creates the operator-internal `platform` Institution and a
superadmin User inside it (is_staff + is_superuser). Idempotent: an existing
superadmin email in the platform tenant is left untouched with a notice.
"""

from accounts.models import Institution, User
from django.core.management.base import BaseCommand
from django.db import transaction

PLATFORM_SLUG = "platform"
PLATFORM_NAME = "Platform"


class Command(BaseCommand):
    help = "Bootstrap the platform superadmin (first operator) and platform tenant."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Superadmin email.")
        parser.add_argument("--password", required=True, help="Superadmin password.")

    def handle(self, *args, **options):
        email = User.objects.normalize_email(options["email"])
        password = options["password"]

        with transaction.atomic():
            platform, created = Institution.objects.get_or_create(
                slug=PLATFORM_SLUG,
                defaults={"name": PLATFORM_NAME, "is_active": True},
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"Created platform institution ({platform.id}).")
                )
            else:
                self.stdout.write(f"Platform institution already exists ({platform.id}); reusing.")

            superadmin = User.objects.filter(tenant=platform, email=email).first()
            if superadmin is not None:
                self.stdout.write(
                    f"Superadmin {email} already exists in platform; skipping."
                )
            else:
                superadmin = User.objects.create_superuser(
                    tenant=platform,
                    email=email,
                    password=password,
                    role=User.Role.SUPERADMIN,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Created superadmin {email}.")
                )

        self.stdout.write(
            f"institution_id={platform.id} login_slug={PLATFORM_SLUG}"
        )
