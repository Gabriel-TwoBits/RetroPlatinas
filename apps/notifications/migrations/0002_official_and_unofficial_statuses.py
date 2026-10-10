from django.db import migrations

KIND_STATUS = "status"
# Mirrors achievements 0008: community and verified were both official.
FORWARD = {"draft": "unofficial", "community": "official", "verified": "official"}
BACKWARD = {"unofficial": "draft", "official": "community"}
STATUS_PARAMS = ("old_status", "new_status")


def _convert(apps, mapping):
    notification_model = apps.get_model("notifications", "Notification")
    # TRADEOFF: every status notification in memory at once; batch it if they reach millions.
    changed = []
    for notification in notification_model.objects.filter(kind=KIND_STATUS):
        for param in STATUS_PARAMS:
            status = notification.params.get(param)
            notification.params[param] = mapping.get(status, status)
        changed.append(notification)
    notification_model.objects.bulk_update(changed, ["params"])


def to_official_and_unofficial(apps, schema_editor):
    _convert(apps, FORWARD)


def to_draft_and_community(apps, schema_editor):
    _convert(apps, BACKWARD)


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(to_official_and_unofficial, to_draft_and_community),
    ]
