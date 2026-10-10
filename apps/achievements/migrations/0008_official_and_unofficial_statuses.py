from django.db import migrations, models

STATUS_CHOICES = [("official", "Official"), ("unofficial", "Unofficial")]
# Community and verified were both awarded and worth points; the seal is not kept, so a
# revision that only moved between them now repeats the one before it.
FORWARD = {"draft": "unofficial", "community": "official", "verified": "official"}
BACKWARD = {"unofficial": "draft", "official": "community"}


def _convert(apps, mapping):
    for model_name in ("Achievement", "AchievementRevision"):
        model = apps.get_model("achievements", model_name)
        for old, new in mapping.items():
            model.objects.filter(status=old).update(status=new)


def to_official_and_unofficial(apps, schema_editor):
    _convert(apps, FORWARD)


def to_draft_and_community(apps, schema_editor):
    _convert(apps, BACKWARD)


class Migration(migrations.Migration):
    dependencies = [
        ("achievements", "0007_achievement_revision"),
    ]

    operations = [
        migrations.AlterField(
            model_name="achievement",
            name="status",
            field=models.CharField(
                choices=STATUS_CHOICES,
                default="unofficial",
                max_length=16,
                verbose_name="status",
            ),
        ),
        migrations.AlterField(
            model_name="achievementrevision",
            name="status",
            field=models.CharField(choices=STATUS_CHOICES, max_length=16, verbose_name="status"),
        ),
        migrations.RunPython(to_official_and_unofficial, to_draft_and_community),
    ]
