/** @odoo-module **/
/* Copyright 2026 Nicolás Ramos
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl). */

/**
 * Proactive signal trigger.
 *
 * Fires `POST /odooclaw/signal` whenever the user opens a screen whose
 * area is known to the proactive engine.  The Go backend decides whether
 * to speak; Odoo itself posts the message inside the user's request scope.
 *
 * The component reads `odooclaw.proactive_url` from ir.config_parameter so
 * the URL can be changed without redeploying.
 */

import { useEffect } from "@web/core/utils/hooks";
import { useService } from "@web/framework/auth_service";

export const proactiveSignal = {
    template: "mail_bot_odooclaw.ProactiveSignal",
    setup() {
        const config = useService("config");

        useEffect(() => {
            const proactiveUrl = config.get("odooclaw.proactive_url");
            if (!proactiveUrl) {
                return; // not configured — silently skip
            }

            const area = config.get("odooclaw.proactive_area");
            if (!area) {
                return; // no area registered for this screen
            }

            fetch(proactiveUrl + "/signal", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ area }),
            }).catch((err) => {
                // Silently fail: the user experience must not break when the
                // engine is unreachable.  The Go side already has its own logs.
                console.debug("[odooclaw/proactive] signal failed:", err);
            });
        }, []);
    },
};
