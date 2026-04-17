from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_lead_scoring_and_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="website_quality",
            field=models.CharField(default="unknown", max_length=20),
        ),
        migrations.AddField(
            model_name="emaillog",
            name="scheduled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="emaillog",
            name="status",
            field=models.CharField(max_length=50),
        ),
        migrations.CreateModel(
            name="LeadTask",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("task_type", models.CharField(max_length=20, choices=[("whatsapp", "WhatsApp"), ("call", "Call")])),
                ("status", models.CharField(max_length=20, choices=[("pending", "Pending"), ("done", "Done")], default="pending")),
                ("notes", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "lead",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="tasks", to="core.lead"),
                ),
            ],
        ),
    ]

