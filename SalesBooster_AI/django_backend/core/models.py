from django.db import models
from django.contrib.auth.models import User

class Lead(models.Model):
    STATUS_NEW = "new"
    STATUS_CONTACTED = "contacted"
    STATUS_REPLIED = "replied"
    STATUS_MEETING = "meeting"
    STATUS_WON = "won"
    STATUS_LOST = "lost"
    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_REPLIED, "Replied"),
        (STATUS_MEETING, "Meeting"),
        (STATUS_WON, "Won"),
        (STATUS_LOST, "Lost"),
    ]

    keyword = models.CharField(max_length=255, db_index=True)
    source_url = models.URLField(max_length=500)
    contact_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True, null=True)
    lead_score = models.IntegerField(default=0)
    intent_type = models.CharField(max_length=50, default="awareness")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leads')

    def __str__(self):
        return f"{self.email} ({self.keyword})"

class EmailLog(models.Model):
    target_email = models.EmailField()
    subject = models.CharField(max_length=500)
    status = models.CharField(max_length=50) # success/failed
    campaign_name = models.CharField(max_length=100, default="default")
    sequence_step = models.IntegerField(default=1)
    error_msg = models.TextField(blank=True, null=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
