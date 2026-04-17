from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from core.models import Lead
from core.utils import compute_lead_score


class Command(BaseCommand):
    help = "Create sample leads for demos (Lead Manager empty state)."

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, default="", help="Django username to attach leads to.")
        parser.add_argument("--count", type=int, default=5, help="How many demo rows to create (default 5).")

    def handle(self, *args, **options):
        username = (options.get("username") or "").strip()
        count = max(1, min(20, int(options.get("count") or 5)))
        if not username:
            self.stderr.write("Pass --username YOUR_LOGIN (must exist). Example: python manage.py seed_demo_leads --username admin")
            return
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stderr.write(f"No user named {username!r}. Register in the app first, then re-run.")
            return

        demos = [
            ("https://example-agency.com", "Alex Rivera", "alex@example-agency.com", "+1-415-555-0101"),
            ("https://northwind-cafe.example", "Sam Lee", "sam@northwind-cafe.example", "+44-20-7946-0958"),
            ("https://bright-smiles-dental.example", "Priya Shah", "contact@bright-smiles-dental.example", ""),
            ("https://summit-fitness.example", "Jordan Mills", "not_found", "+1-206-555-0199"),
            ("https://pixelcraft-studio.example", "Casey Ng", "hello@pixelcraft-studio.example", "+65-6123-4567"),
        ]
        created = 0
        for i in range(count):
            url, name, email, phone = demos[i % len(demos)]
            if Lead.objects.filter(owner=user, source_url=url, email=email).exists():
                continue
            score, intent = compute_lead_score(email, phone, url, "Demo seed")
            Lead.objects.create(
                keyword="Demo seed",
                source_url=url,
                contact_name=name,
                email=email if email != "not_found" else "not_found",
                phone=phone or "not_found",
                owner=user,
                lead_score=score,
                intent_type=intent,
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} demo lead(s) for {username!r}."))
