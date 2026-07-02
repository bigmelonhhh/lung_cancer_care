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

    def test_portal_installs_htmx_alpine_lifecycle_bridge(self):
        portal = self._read("templates/layouts/base_portal.html")

        self.assertIn("installHtmxAlpineLifecycleBridge", portal)
        self.assertIn("window.__htmxAlpineLifecycleBridgeInstalled", portal)
        self.assertIn("document.addEventListener('htmx:beforeSwap'", portal)
        self.assertIn("Alpine.stopObservingMutations();", portal)
        self.assertIn("prepareAlpineTreeForDestroy(target);", portal)
        self.assertIn("node._x_lookup = {};", portal)
        self.assertIn("Alpine.destroyTree(target)", portal)
        self.assertIn("isKnownAlpineCleanupRace(error)", portal)
        self.assertIn("document.addEventListener('htmx:afterSwap'", portal)
        self.assertIn("Alpine.initTree(target)", portal)
        self.assertIn("Alpine.startObservingMutations();", portal)
        self.assertIn("logLifecycleWarning('alpine destroyTree failed', error);", portal)
        self.assertNotIn("failed to load alpine for htmx lifecycle bridge", portal)
        self.assertNotIn("ensureMany(['alpineCollapse', 'alpine']).then", portal)

    def test_reports_history_manual_replacement_owns_alpine_init_only_for_manual_swaps(self):
        reports_history = self._read("static/web_doctor/reports_history.js")

        self.assertIn("Alpine.mutateDom(swapContent);", reports_history)
        self.assertIn("Alpine.destroyTree(target);", reports_history)
        self.assertIn("target.innerHTML = html;", reports_history)
        self.assertIn("processNode(target);", reports_history)
        self.assertNotIn(
            'if (target && target.id === "reports-history-content") {\n      processNode(target);\n    }',
            reports_history,
        )

    def test_reports_history_lifecycle_errors_do_not_trigger_detail_load_failure(self):
        reports_history = self._read("static/web_doctor/reports_history.js")

        self.assertIn('logLifecycleWarning("alpine destroyTree failed", error);', reports_history)
        self.assertIn('logLifecycleWarning("alpine initTree failed", error);', reports_history)
        self.assertIn('logLifecycleWarning("htmx process failed", error);', reports_history)
        self.assertIn("replaceContent(target, html);", reports_history)
        self.assertIn('target.dataset.loaded = "1";', reports_history)

    def test_reports_history_row_detail_avoids_alpine_collapse_transitions(self):
        row_template = self._read("templates/web_doctor/partials/reports_history/_record_row.html")

        self.assertIn('x-show="expanded"', row_template)
        self.assertNotIn("x-collapse", row_template)
        self.assertNotIn("transitioning: false", row_template)
        self.assertIn("await window.loadReportsDetail", row_template)
        self.assertIn("finally {", row_template)
        self.assertIn("this.loadingDetail = false;", row_template)

    def test_doctor_workspace_loads_reports_history_script_from_stable_shell(self):
        workspace = self._read("templates/web_doctor/index.html")

        self.assertIn("{% load static %}", workspace)
        self.assertIn("web_doctor/reports_history.js", workspace)

    def test_reports_history_row_guards_missing_detail_loader(self):
        row_template = self._read("templates/web_doctor/partials/reports_history/_record_row.html")

        self.assertIn("typeof window.loadReportsDetail !== 'function'", row_template)
        self.assertIn("详情加载失败，请刷新后重试。", row_template)
        self.assertIn("this.detailLoaded = false;", row_template)

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
