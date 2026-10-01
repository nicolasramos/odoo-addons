"""QA probe (temporary, NOT part of the PR under review)

Smoke test for embed_semantic_search: verifies the JS module loads
and the IndexedDB store is accessible. Run with --test-enable in a
real Odoo instance.
"""
from odoo import SUPERUSER_ID, api
from odoo.tests import HttpCase, tagged


PROBE_CODE = """(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const log = (m) => console.log('QAP:' + m);
    try {
        for (let i = 0; i < 60; i++) {
            if (window.odoo && document.querySelector('.o_main_navbar')) break;
            await sleep(500);
        }
        log('url=' + location.pathname);
        log('typeof_EmbedSemanticSearch=' + typeof window.EmbedSemanticSearch);
        log('typeof_runonwebBundle=' + typeof window.runonwebBundle);
        log('typeof_runonwebBridge=' + typeof window.runonwebBridge);
        let b = window.runonwebBridge;
        log('typeof_window_odoo=' + typeof window.odoo);
        log('typeof_bundle_inject=' + (window.runonwebBundle ? typeof window.runonwebBundle.injectRunonwebBridge : 'n/a'));
        if (!b && window.runonwebBundle && typeof window.runonwebBundle.injectRunonwebBridge === 'function') {
            try {
                await window.runonwebBundle.injectRunonwebBridge();
                b = window.runonwebBridge;
                log('bridge_injected=true');
            } catch (e) {
                log('bridge_inject_error=' + e.message);
            }
        }
        if (b) {
            log('bridge_importEmbed=' + typeof b.importEmbed);
            log('bridge_features=' + JSON.stringify(b.features));
        } else {
            log('bridge_null');
        }
        // Try to get the embed engine (may fail if runonweb/embed not loaded)
        try {
            const es = window.runonwebBundle && typeof window.runonwebBundle.getEmbedSemanticSearch === 'function'
                ? window.runonwebBundle.getEmbedSemanticSearch()
                : null;
            log('embed_engine=' + (es ? 'found' : 'not_found'));
            if (es) {
                log('embed_modelReady=' + es._modelReady);
                log('embed_webgpu=' + (typeof es.checkWebGPU === 'function' ? 'yes' : 'no'));
            }
        } catch (e) {
            log('embed_engine_error=' + e.message);
        }
        // Check IndexedDB availability
        try {
            const hasIDB = typeof indexedDB !== 'undefined';
            log('indexedDB_available=' + hasIDB);
            if (hasIDB) {
                const req = indexedDB.open('runonweb_embed_vectors_test', 1);
                req.onsuccess = () => { log('IDB_open_success'); req.result.close(); };
                req.onerror = () => { log('IDB_open_error=' + req.error); };
            }
        } catch (e) {
            log('IDB_check_error=' + e.message);
        }
    } catch (e) {
        log('probe_error=' + e.message);
    }
    // Signal completion
    window._qa_embed_probe_complete = true;
})();"""


@tagged('-standard', 'mail_bot_odooclaw')
class QASemanticProbe(HttpCase):
    """Smoke probe for embed_semantic_search — NOT a real test."""

    PROBE_URL = "/mail_bot_odooclaw/embed/probe"  # placeholder URL

    def _enable_embed(self):
        """Enable the embed feature flag for testing."""
        Flag = self.env["runonweb.feature.flag"]
        embed_flag = Flag.search([("feature_type", "=", "embed")], limit=1)
        if embed_flag:
            embed_flag.write({"active": True})
        # Also enable globally
        Settings = self.env["runonweb.settings"]
        settings = Settings.search([], limit=1)
        if settings:
            settings.write({"enable_embed": True})

    def test_01_embed_surface(self):
        """Verify embed JS is loaded on Discuss page."""
        # This test verifies the JS module is present in assets
        # The actual probe runs via browser_js
        self._enable_embed()
        self.browser_js(
            self.PROBE_URL,
            PROBE_CODE,
            login="admin",
            timeout=300,
        )
