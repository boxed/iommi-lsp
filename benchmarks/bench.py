"""Per-keystroke latency benchmark for iommi_lsp completions.

Run with: ``python -m benchmarks.bench`` or ``python benchmarks/bench.py``.

Builds a synthetic workspace, wires up the same analyzer chain as the CLI,
and times :meth:`CompletionMatchmaker._gather` at hot cursor positions —
that's the synchronous work the proxy does on every keystroke before it
either short-circuits the response or forwards the request to ty.

Each scenario reports min / p50 / p95 / max in milliseconds. The script
exits non-zero when any scenario's p95 exceeds ``MAX_P95_MS`` so it can
double as a CI smoke test.

The benchmark deliberately measures ``_gather`` rather than going through
the full bytes->JSON->bytes path, because the JSON overhead is a small
constant and the per-keystroke variance is dominated by analyzer work.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# Make ``src/`` importable when invoked directly from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from iommi_lsp.analyzers.admin import AdminAnalyzer
from iommi_lsp.analyzers.django import DjangoAnalyzer
from iommi_lsp.analyzers.forms import FormsAnalyzer
from iommi_lsp.analyzers.iommi import IommiAnalyzer
from iommi_lsp.analyzers.migrations import MigrationsAnalyzer
from iommi_lsp.analyzers.settings import SettingsAnalyzer
from iommi_lsp.analyzers.signals import SignalsAnalyzer
from iommi_lsp.analyzers.templates import TemplateAnalyzer
from iommi_lsp.analyzers.urls import UrlAnalyzer
from iommi_lsp.analyzers.views import ViewsAnalyzer
from iommi_lsp.interceptor import CompletionMatchmaker, DocumentStore


# Any scenario whose p95 exceeds this is treated as a regression. The
# threshold is intentionally loose — we care about "do users feel typing
# stutter" not microbenchmark accuracy. 20 ms per keystroke is roughly
# the boundary where popups start visibly lagging behind keypresses.
MAX_P95_MS = 20.0


# ---------------------------------------------------------------------------
# Synthetic workspace.
# ---------------------------------------------------------------------------


_URL_NAMES = [f"view_{i:03d}" for i in range(100)]


_SETTINGS_PY = """\
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "myapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
]

ROOT_URLCONF = "urls"
DEBUG = True
SECRET_KEY = "x"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
"""


_ROOT_URLS_PY = """\
from django.urls import include, path

urlpatterns = [
    path("", include("myapp.urls")),
]
"""


def _myapp_urls_py() -> str:
    lines = [
        "from django.urls import path",
        "from . import views",
        "",
        "urlpatterns = [",
    ]
    for name in _URL_NAMES:
        lines.append(f"    path('{name}/', views.placeholder, name='{name}'),")
    lines.append("]")
    return "\n".join(lines) + "\n"


_MODELS_PY = """\
from django.db import models


class User(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField()


class Post(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
"""


def _views_py(extra_body: str = "") -> str:
    """A realistic views.py with imports, a couple of CBVs, and the
    cursor area appended at the bottom via *extra_body*."""
    return f"""\
from __future__ import annotations

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import ListView, DetailView

from .models import Post, Profile, User


def placeholder(request):
    return HttpResponse(b"placeholder")


def home(request):
    url = reverse('view_001')
    return redirect(url)


class PostList(ListView):
    model = Post
    paginate_by = 25
    template_name = "myapp/post_list.html"


class PostDetail(DetailView):
    model = Post
    template_name = "myapp/post_detail.html"


def show_profile(request, pk):
    profile = Profile.objects.get(pk=pk)
    return render(request, "myapp/profile.html", {{"profile": profile}})


{extra_body}
"""


def _huge_views_py(extra_body: str) -> str:
    """A 3000+ LoC views.py — exercises the AST-parse cost at scale."""
    repeat_block = """

def handler_{i}(request, post_id):
    post = Post.objects.get(pk=post_id)
    user = post.author
    if user.is_active:
        return JsonResponse({{"ok": True, "user": user.username}})
    return redirect("home")
""".strip("\n")
    chunks = [_views_py("")]
    for i in range(200):
        chunks.append(repeat_block.format(i=i))
    chunks.append(extra_body)
    return "\n".join(chunks) + "\n"


_FORMS_PY = """\
from iommi import Form
from .models import User, Post


def make_user_form():
    return Form.create(auto__model=User)


def make_post_form():
    return Form.create(auto__model=Post, auto__include=['title', 'body'])
"""


_MYAPP_EXTRAS_PY = """\
from django import template

register = template.Library()


@register.filter
def shout(value):
    return value.upper()


@register.filter(name='excited')
def add_exclamation(value):
    return f"{value}!"


@register.filter
def reversed_string(value):
    return value[::-1]
"""


_LAYOUT_HTML = """\
<!doctype html>
<html>
  <head><title>{% block title %}{% endblock %}</title></head>
  <body>
    {% block header %}{% endblock %}
    {% block content %}{% endblock %}
    {% block sidebar %}{% endblock %}
    {% block footer %}{% endblock %}
  </body>
</html>
"""


def _page_html(extra_body: str = "") -> str:
    """Realistic page template that extends a layout, loads a custom
    library, and uses both built-in and library filters. The cursor area
    appends at the bottom via *extra_body*."""
    return (
        "{% extends 'myapp/_layout.html' %}\n"
        "{% load myapp_extras %}\n"
        "\n"
        "{% block content %}\n"
        "  <h1>{{ title|upper }}</h1>\n"
        "  <p>{{ body|truncatewords:50 }}</p>\n"
        f"{extra_body}"
        "{% endblock %}\n"
    )


def _huge_page_html(extra_body: str = "") -> str:
    """A 600+ line page template — exercises the linear-cost helpers
    (``{% load %}`` regex scan, ``_enclosing_template_*`` reverse
    finds) at scale."""
    repeat_block = (
        "  <article>\n"
        "    <h2>{{ post.title|capfirst|truncatewords:8 }}</h2>\n"
        "    <p>{{ post.body|safe|linebreaks }}</p>\n"
        "    {% if post.author %}<span>{{ post.author|shout }}</span>{% endif %}\n"
        "  </article>\n"
    )
    chunks = [_page_html("")]
    for _ in range(200):
        chunks.append(repeat_block)
    chunks.append(extra_body)
    return "".join(chunks)


def write_workspace(root: Path) -> None:
    """Materialise the synthetic Django project under *root*."""
    (root / "settings.py").write_text(_SETTINGS_PY)
    (root / "urls.py").write_text(_ROOT_URLS_PY)
    myapp = root / "myapp"
    myapp.mkdir()
    (myapp / "__init__.py").write_text("")
    (myapp / "models.py").write_text(_MODELS_PY)
    (myapp / "urls.py").write_text(_myapp_urls_py())
    (myapp / "views.py").write_text(_views_py())
    (myapp / "forms.py").write_text(_FORMS_PY)
    # templatetags package — the source of custom-filter completions.
    tt = myapp / "templatetags"
    tt.mkdir()
    (tt / "__init__.py").write_text("")
    (tt / "myapp_extras.py").write_text(_MYAPP_EXTRAS_PY)
    # Templates — _layout.html is the extends parent (so {% block %}
    # completion has something to walk into), page.html is a realistic
    # child template used as a known-template-name target.
    templates_dir = myapp / "templates" / "myapp"
    templates_dir.mkdir(parents=True)
    (templates_dir / "_layout.html").write_text(_LAYOUT_HTML)
    (templates_dir / "page.html").write_text(_page_html())


# ---------------------------------------------------------------------------
# Analyzer wiring — mirrors cli._run_proxy so the benchmark exercises the
# same code path the editor hits.
# ---------------------------------------------------------------------------


def build_matchmaker(root: Path) -> tuple[CompletionMatchmaker, DocumentStore, list]:
    documents = DocumentStore()
    django = DjangoAnalyzer(workspace_root=root, text_provider=documents.get)
    iommi = IommiAnalyzer(
        workspace_root=root,
        text_provider=documents.get,
        django_index_provider=lambda: django.django_index,
        auto_build=False,
    )
    urls = UrlAnalyzer(workspace_root=root, text_provider=documents.get)
    templates = TemplateAnalyzer(
        workspace_root=root,
        text_provider=documents.get,
        # Mirrors cli._run_proxy: the template analyzer's `{% url %}`
        # completion + diagnostic feed off the URL index.
        url_index_provider=lambda: urls.url_index,
    )
    settings = SettingsAnalyzer(
        workspace_root=root,
        text_provider=documents.get,
        django_index_provider=lambda: django.django_index,
    )
    admin = AdminAnalyzer(
        workspace_root=root,
        text_provider=documents.get,
        django_index_provider=lambda: django.django_index,
    )
    forms = FormsAnalyzer(
        workspace_root=root,
        text_provider=documents.get,
        django_index_provider=lambda: django.django_index,
    )
    views = ViewsAnalyzer(
        workspace_root=root,
        text_provider=documents.get,
        django_index_provider=lambda: django.django_index,
    )
    signals = SignalsAnalyzer(
        workspace_root=root,
        text_provider=documents.get,
        django_index_provider=lambda: django.django_index,
    )
    migrations = MigrationsAnalyzer(workspace_root=root, text_provider=documents.get)
    # Mirror the order in iommi_lsp.cli._run_proxy so the benchmark
    # reflects the real per-keystroke path. Keep this list in sync when
    # the production order changes.
    analyzers = [
        urls, templates, settings,
        admin, forms, views, signals, migrations,
        iommi, django,
    ]
    matchmaker = CompletionMatchmaker(analyzers=analyzers, text_provider=documents.get)
    return matchmaker, documents, analyzers


async def index_all(analyzers, root: Path) -> None:
    for a in analyzers:
        await a.index(root)


# ---------------------------------------------------------------------------
# Scenarios.
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    relpath: str
    text: str
    cursor: tuple[int, int]


def _cursor_for(text: str, marker: str = "<CURSOR>") -> tuple[str, tuple[int, int]]:
    """Strip *marker* from *text* and return (clean text, (line, character)).

    Lets scenarios mark the cursor inline without counting columns by hand.
    """
    idx = text.index(marker)
    head = text[:idx]
    line = head.count("\n")
    last_nl = head.rfind("\n")
    character = len(head) - (last_nl + 1)
    return text.replace(marker, "", 1), (line, character)


def _build_scenarios() -> list[Scenario]:
    out: list[Scenario] = []

    # 1. reverse('|')  — empty arg, baseline for the URL hot path.
    text, cur = _cursor_for(
        _views_py("def x():\n    return reverse('<CURSOR>')\n")
    )
    out.append(Scenario("reverse-empty", "myapp/views.py", text, cur))

    # 2. reverse('re|')  — the exact partial the user reported as slow.
    text, cur = _cursor_for(
        _views_py("def x():\n    return reverse('re<CURSOR>')\n")
    )
    out.append(Scenario("reverse-partial-re", "myapp/views.py", text, cur))

    # 3. reverse('view_0|')  — late-typing partial.
    text, cur = _cursor_for(
        _views_py("def x():\n    return reverse('view_0<CURSOR>')\n")
    )
    out.append(Scenario("reverse-partial-late", "myapp/views.py", text, cur))

    # 4. reverse inside a *large* file — same hot path but the buffer is
    # 200x larger, so any analyzer that ast.parses the buffer pays for it.
    text, cur = _cursor_for(
        _huge_views_py("def x():\n    return reverse('re<CURSOR>')\n")
    )
    out.append(Scenario("reverse-partial-re-big-file", "myapp/views.py", text, cur))

    # 5. INSTALLED_APPS string literal — settings analyzer claims this.
    settings_text, cur = _cursor_for(
        _SETTINGS_PY.replace(
            '"django.contrib.admin",',
            '"<CURSOR>",',
        )
    )
    out.append(Scenario("installed-apps-empty", "settings.py", settings_text, cur))

    # 6. Django ORM kwarg — Model.objects.filter(|).
    text, cur = _cursor_for(
        _views_py("def y():\n    return User.objects.filter(<CURSOR>)\n")
    )
    out.append(Scenario("orm-kwarg-empty", "myapp/views.py", text, cur))

    # 7. iommi Form auto__ kwarg — exercises the iommi analyzer.
    text, cur = _cursor_for(
        _FORMS_PY.replace(
            "Form.create(auto__model=User)",
            "Form.create(auto__<CURSOR>)",
        )
    )
    out.append(Scenario("iommi-auto-kwarg", "myapp/forms.py", text, cur))

    # 8. Non-completion position — cursor in the middle of a def line, far
    # from any string. All analyzers should bail out cheaply; this is the
    # floor we shouldn't sink below.
    text, cur = _cursor_for(_views_py("def some_<CURSOR>function():\n    pass\n"))
    out.append(Scenario("baseline-no-context", "myapp/views.py", text, cur))

    # 9. Top-level partial identifier inside a *big* file — no string, no
    # call site, nothing for any analyzer to claim. This is the shape
    # users hit when typing an import name between imports in a 1k-line
    # models.py. Every analyzer that ast.parses the buffer pays the cost
    # because none can bail before deciding the position is "not theirs".
    text, cur = _cursor_for(
        _huge_views_py("\nrever<CURSOR>\n")
    )
    out.append(Scenario("top-level-rever-big-file", "myapp/views.py", text, cur))

    # ---- Django template tag scenarios (html files) -----------------------
    # All of these go through TemplateAnalyzer alone — the other analyzers
    # bail before doing any work because the URI doesn't end in ``.py``.
    # Relpath points into ``templates/myapp/`` so ``_uri_to_path`` lands
    # on a known template-extension file.

    # 10. {% url '<CURSOR>' %} — exercises tag detection + URL index lookup.
    text, cur = _cursor_for(
        "<a href=\"{% url '<CURSOR>' %}\">x</a>\n"
    )
    out.append(Scenario(
        "template-url-tag-empty", "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 11. {% extends '<CURSOR>' %} — template-name completion.
    text, cur = _cursor_for("{% extends '<CURSOR>' %}\n")
    out.append(Scenario(
        "template-extends-empty", "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 12. {% block <CURSOR> %} after extends — exercises the parent-template
    # read + ``_block_names_in`` regex on the parent.
    text, cur = _cursor_for(
        "{% extends 'myapp/_layout.html' %}\n"
        "{% block <CURSOR>\n"
    )
    out.append(Scenario(
        "template-block-empty", "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 13. {% load <CURSOR> %} — templatetags package list.
    text, cur = _cursor_for("{% load <CURSOR>\n")
    out.append(Scenario(
        "template-load-empty", "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 14. {{ x|<CURSOR> }} with no {% load %} — built-in filters only.
    # The active path here is the variable-expression detector +
    # ``_loaded_libraries`` regex scan on the buffer.
    text, cur = _cursor_for("{{ name|<CURSOR> }}\n")
    out.append(Scenario(
        "template-filter-no-load", "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 15. {{ x|<CURSOR> }} *after* a {% load %} — exercises the same path
    # plus the union with library-discovered filters.
    text, cur = _cursor_for(
        "{% load myapp_extras %}\n"
        "{{ name|<CURSOR> }}\n"
    )
    out.append(Scenario(
        "template-filter-with-load", "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 16. {{ x|tr<CURSOR> }} — partial filter narrowing built-ins.
    text, cur = _cursor_for("{{ name|tr<CURSOR> }}\n")
    out.append(Scenario(
        "template-filter-partial", "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 17. Filter completion in a *huge* template — the cost the user feels
    # while typing inside a long template. ``_loaded_libraries`` scans
    # the whole buffer, ``_enclosing_template_var`` does an ``rfind``
    # back from the cursor; both are linear in file size.
    text, cur = _cursor_for(
        _huge_page_html("  <p>{{ x|<CURSOR> }}</p>\n")
    )
    out.append(Scenario(
        "template-filter-big-file",
        "myapp/templates/myapp/tag.html", text, cur,
    ))

    # 18. Plain HTML position with no completion intent — floor for the
    # template analyzer's "not my problem" bail-out cost on every keystroke
    # the user makes while editing markup.
    text, cur = _cursor_for("<p>some <CURSOR>text here</p>\n")
    out.append(Scenario(
        "template-baseline-no-context",
        "myapp/templates/myapp/tag.html", text, cur,
    ))

    return out


# ---------------------------------------------------------------------------
# Timing.
# ---------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    samples: list[float]   # milliseconds

    @property
    def min(self) -> float:
        return min(self.samples)

    @property
    def p50(self) -> float:
        return statistics.median(self.samples)

    @property
    def p95(self) -> float:
        if len(self.samples) < 20:
            return max(self.samples)
        return statistics.quantiles(self.samples, n=20)[-1]

    @property
    def max(self) -> float:
        return max(self.samples)


def _file_uri(root: Path, relpath: str) -> str:
    return (root / relpath).resolve().as_uri()


def run_scenario(
    matchmaker: CompletionMatchmaker,
    documents: DocumentStore,
    root: Path,
    scenario: Scenario,
    *,
    warmup: int = 20,
    iterations: int = 200,
) -> Result:
    uri = _file_uri(root, scenario.relpath)
    documents.did_open(uri, scenario.text)
    position = {"line": scenario.cursor[0], "character": scenario.cursor[1]}
    # Warmup pass first — primes any per-call caches (iommi parsed buffer,
    # interned strings, etc.) so the first measured sample isn't an outlier.
    for _ in range(warmup):
        matchmaker._gather(uri, position)
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        matchmaker._gather(uri, position)
        t1 = time.perf_counter()
        samples.append((t1 - t0) * 1000.0)
    documents.did_close(uri)
    return Result(name=scenario.name, samples=samples)


def run_typing_simulation(
    matchmaker: CompletionMatchmaker,
    documents: DocumentStore,
    root: Path,
    *,
    relpath: str = "myapp/views.py",
    word: str = "view_001",
) -> list[Result]:
    """Type *word* character-by-character inside ``reverse('|')`` and time
    each keystroke's full ``_gather`` call.

    Most directly reproduces the user-visible "slow popup" complaint —
    one Result per keystroke, so it's clear whether latency is uniform
    or spikes at a specific position.
    """
    base = _views_py("def x():\n    return reverse('<CURSOR>')\n")
    base_text, base_cur = _cursor_for(base)
    uri = _file_uri(root, relpath)
    results: list[Result] = []
    for n in range(1, len(word) + 1):
        partial = word[:n]
        text = base_text[:_offset(base_text, base_cur)] + partial + base_text[_offset(base_text, base_cur):]
        cur = (base_cur[0], base_cur[1] + n)
        documents.did_open(uri, text)
        position = {"line": cur[0], "character": cur[1]}
        for _ in range(5):
            matchmaker._gather(uri, position)
        samples: list[float] = []
        for _ in range(50):
            t0 = time.perf_counter()
            matchmaker._gather(uri, position)
            t1 = time.perf_counter()
            samples.append((t1 - t0) * 1000.0)
        documents.did_close(uri)
        results.append(Result(name=f"keystroke-{n}-{partial!r}", samples=samples))
    return results


def _offset(text: str, cursor: tuple[int, int]) -> int:
    line, character = cursor
    pos = 0
    for _ in range(line):
        nl = text.find("\n", pos)
        if nl < 0:
            return len(text)
        pos = nl + 1
    return pos + character


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------


_FMT = "{name:<34} {min:>8.2f} {p50:>8.2f} {p95:>8.2f} {max:>8.2f}   {note}"


def _print_header(title: str) -> None:
    print()
    print(f"## {title}")
    print(f"{'scenario':<34} {'min':>8} {'p50':>8} {'p95':>8} {'max':>8}   note")
    print("-" * 78)


def _print_result(result: Result, threshold: float = MAX_P95_MS) -> bool:
    note = "" if result.p95 <= threshold else f"OVER {threshold:.0f}ms"
    print(_FMT.format(
        name=result.name,
        min=result.min, p50=result.p50, p95=result.p95, max=result.max,
        note=note,
    ))
    return result.p95 <= threshold


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    with tempfile.TemporaryDirectory(prefix="iommi-lsp-bench-") as tmp:
        root = Path(tmp)
        write_workspace(root)
        matchmaker, documents, analyzers = build_matchmaker(root)
        asyncio.run(index_all(analyzers, root))

        print(f"workspace: {root}")
        print(f"analyzers: {len(analyzers)} ({', '.join(a.name for a in analyzers)})")
        print(f"threshold: p95 <= {MAX_P95_MS:.0f} ms per keystroke")

        all_pass = True

        _print_header("Per-position scenarios")
        for scenario in _build_scenarios():
            r = run_scenario(matchmaker, documents, root, scenario)
            ok = _print_result(r)
            all_pass = all_pass and ok

        _print_header("Typing simulation — reverse('view_001') one keystroke at a time")
        for r in run_typing_simulation(matchmaker, documents, root):
            ok = _print_result(r)
            all_pass = all_pass and ok

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
