from django.db import migrations

KIND_STATUS = "status"
# Mirrors achievements 0008: community and verified were both official.
FORWARD = {"draft": "unofficial", "community": "official", "verified": "official"}
BACKWARD = {"unofficial": "draft", "official": "community"}
STATUS_PARAMS = ("old_status", "new_status")


def _convert(apps, mapping):
    """Maps each status param present; returns the notifications whose old and new now match."""
    notification_model = apps.get_model("notifications", "Notification")
    # TRADEOFF: every status notification in memory at once; batch it if they reach millions.
    changed = []
    unchanged_status = []
    for notification in notification_model.objects.filter(kind=KIND_STATUS):
        # A param missing from a malformed row stays missing.
        for param in STATUS_PARAMS:
            if param in notification.params:
                status = notification.params[param]
                notification.params[param] = mapping.get(status, status)
        changed.append(notification)
        if all(param in notification.params for param in STATUS_PARAMS) and (
            notification.params["old_status"] == notification.params["new_status"]
        ):
            unchanged_status.append(notification.pk)
    notification_model.objects.bulk_update(changed, ["params"])
    return unchanged_status


def to_official_and_unofficial(apps, schema_editor):
    # A community <-> verified move only touched the seal, so it now reads official -> official.
    unchanged_status = _convert(apps, FORWARD)
    notification_model = apps.get_model("notifications", "Notification")
    notification_model.objects.filter(pk__in=unchanged_status).delete()


def to_draft_and_community(apps, schema_editor):
    _convert(apps, BACKWARD)


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(to_official_and_unofficial, to_draft_and_community),
    ]
