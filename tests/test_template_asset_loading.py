from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class TemplateAssetLoadingTests(SimpleTestCase):
    def _read(self, relative_path: str) -> str:
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_base_templates_do_not_hardcode_cdn_core_assets(self):
        portal = self._read("templates/layouts/base_portal.html")
        sales = self._read("templates/layouts/base_sales.html")

        forbidden_fragments = (
            "unpkg.com/htmx.org",
            "cdn.jsdelivr.net/npm/@alpinejs/collapse",
            "unpkg.com/alpinejs",
            "cdn.jsdelivr.net/npm/echarts",
        )

        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, portal)
            self.assertNotIn(fragment, sales)

        self.assertIn("layouts/partials/third_party_assets.html", portal)
        self.assertIn("layouts/partials/third_party_assets.html", sales)

    def test_base_templates_preload_collapse_before_alpine_core(self):
        portal = self._read("templates/layouts/base_portal.html")
        sales = self._read("templates/layouts/base_sales.html")

        for content in (portal, sales):
            collapse_idx = content.find("alpineCollapse")
            core_idx = content.find("'alpine'")
            self.assertNotEqual(collapse_idx, -1)
            self.assertNotEqual(core_idx, -1)
            self.assertLess(collapse_idx, core_idx)

    def test_base_templates_preload_htmx_early_and_alpine_after_dom_ready(self):
        portal = self._read("templates/layouts/base_portal.html")
        sales = self._read("templates/layouts/base_sales.html")

        for content in (portal, sales):
            self.assertIn("window.LCCAssetLoader.ensure('htmx')", content)
            self.assertIn("document.readyState === 'loading'", content)
            self.assertIn(
                "document.addEventListener('DOMContentLoaded', ensureAlpineStack, { once: true });",
                content,
            )
            self.assertIn(
                "window.LCCAssetLoader.ensureMany(['alpineCollapse', 'alpine'])",
                content,
            )

    def test_base_doctor_has_sync_jquery_chain_with_fallbacks(self):
        doctor = self._read("templates/layouts/base_doctor.html")
        local_idx = doctor.find("vendor/jquery/3.7.1/jquery.min.js")
        code_idx = doctor.find("code.jquery.com/jquery-3.7.1.min.js")
        jsdelivr_idx = doctor.find("cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js")

        self.assertNotEqual(local_idx, -1)
        self.assertNotEqual(code_idx, -1)
        self.assertNotEqual(jsdelivr_idx, -1)
        self.assertLess(local_idx, code_idx)
        self.assertLess(code_idx, jsdelivr_idx)

    def test_third_party_assets_declare_collapse_before_alpine(self):
        assets = self._read("templates/layouts/partials/third_party_assets.html")
        collapse_idx = assets.find("alpineCollapse")
        alpine_idx = assets.find("alpine: {")

        self.assertNotEqual(collapse_idx, -1)
        self.assertNotEqual(alpine_idx, -1)
        self.assertLess(collapse_idx, alpine_idx)

    def test_templates_do_not_use_runtime_now_u_cache_buster(self):
        templates_root = Path(settings.BASE_DIR) / "templates"
        for path in templates_root.rglob("*.html"):
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("?v={% now 'U' %}", content, msg=str(path))
