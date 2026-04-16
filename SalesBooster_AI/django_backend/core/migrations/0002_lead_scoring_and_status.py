from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="intent_type",
            field=models.CharField(default="awareness", max_length=50),
        ),
        migrations.AddField(
            model_name="lead",
            name="lead_score",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="lead",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "New"),
                    ("contacted", "Contacted"),
                    ("replied", "Replied"),
                    ("meeting", "Meeting"),
                    ("won", "Won"),
                    ("lost", "Lost"),
                ],
                default="new",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="emaillog",
            name="campaign_name",
            field=models.CharField(default="default", max_length=100),
        ),
        migrations.AddField(
            model_name="emaillog",
            name="sequence_step",
            field=models.IntegerField(default=1),
        ),
    ]
