"""The documentation pages under /docs/, in navigation order."""

from collections.abc import Callable
from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

from apps.achievements.models import Achievement
from apps.games.models import GameHash

GETTING_STARTED = "getting-started"


def _no_extra_context(request):
    return {}


def _getting_started_context(request):
    # The address DuckStation needs as its [Cheevos] Host: this site's origin, no trailing slash.
    return {"server_url": request.build_absolute_uri("/").rstrip("/")}


def _statuses_context(request):
    # Unsaved achievements, one per status, so the page shows the site's own status chips.
    samples = {status: Achievement(status=status) for status, _label in Achievement.STATUS_CHOICES}
    return {"status_samples": samples}


def _faq_context(request):
    discs = GameHash.objects.select_related("game__console").order_by("game__title", "label")
    return {"supported_discs": discs}


@dataclass(frozen=True)
class DocPage:
    slug: str
    title: str
    summary: str
    extra_context: Callable[..., dict] = field(default=_no_extra_context)

    @property
    def template(self):
        return f"docs/{self.slug}.html"


DOC_PAGES = (
    DocPage(
        GETTING_STARTED,
        _("How to start playing"),
        _("Create an account, point DuckStation at this site, log in and play."),
        _getting_started_context,
    ),
    DocPage(
        "creating-achievements",
        _("Creating achievements"),
        _("Write a condition in the web editor, test it unofficial and make it official."),
    ),
    DocPage(
        "statuses-and-contributing",
        _("Statuses and contributing"),
        _("What official and unofficial mean, and how code notes help a set."),
        _statuses_context,
    ),
    DocPage(
        "leaderboards-and-rich-presence",
        _("Leaderboards and rich presence"),
        _("How scores and times are ranked, and what the playing-now line shows."),
    ),
    DocPage(
        "faq",
        _("Frequently asked questions"),
        _("Supported discs, achievements that did not unlock, hardcore and softcore."),
        _faq_context,
    ),
)
DOC_PAGES_BY_SLUG = {page.slug: page for page in DOC_PAGES}
