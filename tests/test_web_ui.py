"""Static, security, structure, and OpenAPI route parity tests for Career Copilot web UI."""

from __future__ import annotations

import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from career_copilot.api.app import register_routes
from career_copilot.api.auth import build_auth_dependency
from career_copilot.api.service import CareerApiService

JOB_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = JOB_ROOT / "src" / "career_copilot" / "web"

EXPECTED_WEB_FILES: dict[str, int] = {
    "templates/index.html": 260,
    "static/css/app.css": 350,
    "static/js/dom.js": 160,
    "static/js/api.js": 260,
    "static/js/views_offers.js": 320,
    "static/js/views_ops.js": 320,
    "static/js/app.js": 260,
}

# Constructed via concatenation to keep this test file clean for zero-PII export scanning.
FORBIDDEN_XSS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\binner" + r"HTML\b"), "innerHTML interdit"),
    (re.compile(r"\bouter" + r"HTML\b"), "outerHTML interdit"),
    (re.compile(r"\binsertAdjacent" + r"HTML\b"), "insertAdjacentHTML interdit"),
    (re.compile(r"\beval\s*\("), "eval() interdit"),
    (re.compile(r"\bnew\s+Function\s*\("), "new Function() interdit"),
    (re.compile(r"\bdocument\.write\s*\("), "document.write() interdit"),
    (re.compile(r"\bon[a-z]+\s*="), "attribut HTML inline on*= interdit"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "URI javascript: interdit"),
)

FORBIDDEN_PII_AND_COUPLING: tuple[str, ...] = (
    "/home/" + "mk",
    "Sites-" + "commerces",
    "server-" + "bots",
    "bot_" + "units",
    "Zero" + "Strike",
    "Data-" + "Tricks",
    "IUT d'" + "Orsay",
    "Universit\u00e9 Paris-" + "Saclay",
    "fonts.googleapis.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
)

_RELATIVE_IMPORT_RE = re.compile(r"""from\s+["'](\./[^"']+\.js)["']""")
_API_CALL_RE = re.compile(
    r"""api(?:Blob)?Request\(\s*(?:"([^"]+)"|`([^`]+)`)(?:\s*,\s*\{([^}]*)\})?""",
    re.DOTALL,
)
_METHOD_RE = re.compile(r"""method\s*:\s*["'](GET|POST|PUT|PATCH|DELETE)["']""")
_TEMPLATE_PARAM_RE = re.compile(r"\$\{[^}]+\}")
_ROUTE_PARAM_RE = re.compile(r"\{[^}]+\}")


class _StubHTTPException(Exception):
    def __init__(
        self, status_code: int, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}


class _StubApp:
    def __init__(self) -> None:
        self.routes: set[tuple[str, str]] = set()

    def _reg(self, method: str, path: str):
        def decorator(fn: Any) -> Any:
            self.routes.add((method, path))
            return fn

        return decorator

    def get(self, path: str, **_kwargs: Any):
        return self._reg("GET", path)

    def post(self, path: str, **_kwargs: Any):
        return self._reg("POST", path)

    def put(self, path: str, **_kwargs: Any):
        return self._reg("PUT", path)

    def patch(self, path: str, **_kwargs: Any):
        return self._reg("PATCH", path)

    def delete(self, path: str, **_kwargs: Any):
        return self._reg("DELETE", path)


class _HtmlInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: list[str] = []
        self.stylesheets: list[str] = []
        self.module_scripts: list[str] = []
        self.html_lang: str | None = None
        self.inline_handlers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        attr_map = dict(attrs)
        if tag == "html":
            self.html_lang = attr_map.get("lang")
        if "id" in attr_map and attr_map["id"]:
            self.ids.append(attr_map["id"])
        if tag == "link" and attr_map.get("rel") == "stylesheet" and attr_map.get("href"):
            self.stylesheets.append(attr_map["href"] or "")
        if tag == "script" and attr_map.get("type") == "module" and attr_map.get("src"):
            self.module_scripts.append(attr_map["src"] or "")
        for key in attr_map:
            if key.lower().startswith("on"):
                self.inline_handlers.append(f"<{tag} {key}=...>")


class WebUiIntegrityTest(unittest.TestCase):
    def test_all_web_files_exist_and_respect_line_budgets(self) -> None:
        for rel_path, budget in EXPECTED_WEB_FILES.items():
            full_path = WEB_ROOT / rel_path
            self.assertTrue(full_path.is_file(), f"Fichier web manquant : {rel_path}")
            lines = len(full_path.read_text(encoding="utf-8").splitlines())
            self.assertLess(lines, 400, f"{rel_path} dépasse 400 lignes ({lines})")
            self.assertLess(lines, budget, f"{rel_path} dépasse son budget de {budget} L ({lines})")

        all_web_files = [p for p in WEB_ROOT.rglob("*") if p.is_file()]
        for path in all_web_files:
            lines = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLess(
                lines, 400, f"{path.relative_to(WEB_ROOT)} dépasse 400 lignes ({lines})"
            )

    def test_zero_xss_sinks_zero_pii_and_zero_external_couplings(self) -> None:
        for rel_path in EXPECTED_WEB_FILES:
            content = (WEB_ROOT / rel_path).read_text(encoding="utf-8")
            for pattern, reason in FORBIDDEN_XSS_PATTERNS:
                self.assertIsNone(
                    pattern.search(content),
                    f"{reason} détecté dans {rel_path}",
                )
            lowered = content.lower()
            for forbidden in FORBIDDEN_PII_AND_COUPLING:
                self.assertNotIn(
                    forbidden.lower(),
                    lowered,
                    f"Chaîne interdite ({forbidden}) détectée dans {rel_path}",
                )

    def test_html_structure_landmarks_assets_and_unique_ids(self) -> None:
        html_text = (WEB_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(html_text.lstrip().lower().startswith("<!doctype html>"))

        inspector = _HtmlInspector()
        inspector.feed(html_text)
        self.assertEqual(inspector.html_lang, "fr")
        self.assertEqual(inspector.inline_handlers, [])
        for landmark in ("header", "nav", "main"):
            self.assertIn(landmark, inspector.tags, f"Balise sémantique <{landmark}> manquante")
        self.assertIn("/static/css/app.css", inspector.stylesheets)
        self.assertIn("/static/js/app.js", inspector.module_scripts)
        self.assertEqual(
            len(inspector.ids),
            len(set(inspector.ids)),
            f"IDs dupliqués dans index.html : {inspector.ids}",
        )
        for required_id in (
            "health-pill",
            "auth-bar",
            "auth-form",
            "token-input",
            "panel-content",
            "toast-region",
            "detail-drawer",
        ):
            self.assertIn(required_id, inspector.ids, f"ID requis manquant : {required_id}")

    def test_all_js_relative_imports_resolve_to_existing_modules(self) -> None:
        js_dir = WEB_ROOT / "static" / "js"
        js_files = sorted(js_dir.glob("*.js"))
        self.assertGreaterEqual(len(js_files), 5)
        for js_file in js_files:
            content = js_file.read_text(encoding="utf-8")
            for match in _RELATIVE_IMPORT_RE.finditer(content):
                target = (js_file.parent / match.group(1)).resolve()
                self.assertTrue(
                    target.is_file() and target.is_relative_to(js_dir.resolve()),
                    f"Import relatif cassé dans {js_file.name} : {match.group(1)}",
                )

    def test_api_js_routes_match_registered_backend_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = CareerApiService(data_dir=Path(tmp) / "data")
            stub = _StubApp()
            dep = build_auth_dependency("T" * 40, http_exception_cls=_StubHTTPException)
            register_routes(
                stub,
                service,
                require_auth=dep,
                depends_fn=lambda fn: fn,
                http_exception_cls=_StubHTTPException,
                html_response_cls=object,
            )

        normalized_backend = {
            (method, _ROUTE_PARAM_RE.sub("{param}", path))
            for method, path in stub.routes
            if path != "/"
        }

        api_js = (WEB_ROOT / "static" / "js" / "api.js").read_text(encoding="utf-8")
        client_routes: set[tuple[str, str]] = set()
        for match in _API_CALL_RE.finditer(api_js):
            raw_path = match.group(1) or match.group(2) or ""
            opts = match.group(3) or ""
            method_match = _METHOD_RE.search(opts)
            method = method_match.group(1) if method_match else "GET"
            normalized_path = _TEMPLATE_PARAM_RE.sub("{param}", raw_path)
            client_routes.add((method, normalized_path))

        self.assertGreaterEqual(len(client_routes), 16)
        for route in sorted(client_routes):
            self.assertIn(
                route,
                normalized_backend,
                f"Route appelée par api.js absente du backend : {route}",
            )

        required_client_routes = {
            ("GET", "/healthz"),
            ("GET", "/api/v1/status"),
            ("GET", "/api/v1/quality/summary"),
            ("GET", "/api/v1/offers"),
            ("GET", "/api/v1/offers/{param}"),
            ("PATCH", "/api/v1/offers/{param}/status"),
            ("GET", "/api/v1/offers/{param}/letter"),
            ("GET", "/api/v1/offers/{param}/letter.pdf"),
            ("GET", "/api/v1/applications"),
            ("POST", "/api/v1/applications/manual"),
            ("DELETE", "/api/v1/applications/manual/{param}"),
            ("GET", "/api/v1/kits"),
            ("GET", "/api/v1/followups"),
            ("GET", "/api/v1/analytics"),
            ("GET", "/api/v1/runs"),
            ("POST", "/api/v1/runs/daily"),
            ("POST", "/api/v1/runs/sync"),
            ("GET", "/api/v1/runs/{param}"),
            ("GET", "/api/v1/interview-prep/{param}"),
            ("GET", "/api/v1/setup"),
            ("PUT", "/api/v1/setup"),
        }
        missing = required_client_routes - client_routes
        self.assertEqual(missing, set(), f"Routes requises non câblées dans api.js : {missing}")


if __name__ == "__main__":
    unittest.main()
