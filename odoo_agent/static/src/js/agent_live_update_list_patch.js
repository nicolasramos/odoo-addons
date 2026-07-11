/** @odoo-module **/

/**
 * Live update for the list view of odoo_agent models.
 *
 * The list controller does not know about individual records, so it cannot
 * re-fetch a single row cheaply. Instead, when an ``odoo_agent:notification``
 * arrives, we ask the list model to reload the rows that are currently
 * on screen. Odoo's relational model will only re-read the records that
 * are actually being displayed, so the cost stays bounded.
 *
 * The patch is opt-in: only ``odoo.agent.execution`` and
 * ``odoo.agent.log`` are subscribed, because those are the lists where
 * live updates matter (you watch executions finish, you watch logs
 * stream in). Other models are skipped to keep the websocket quiet.
 */

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";
import { useBus, useService } from "@web/core/utils/hooks";

const AGENT_LIST_MODELS = new Set([
    "odoo.agent.execution",
    "odoo.agent.log",
    "odoo.agent.chat",
]);

const RELOAD_DEBOUNCE_MS = 800;

export const AgentListLiveUpdate = {
    dependencies: [...ListController.dependencies, "agent_live_update"],
};

patch(ListController.prototype, {
    setup() {
        this._super(...arguments);
        this.agentLiveUpdate = useService("agent_live_update");
        this._listReloadTimer = null;
        const model = this.props && this.props.resModel;
        if (AGENT_LIST_MODELS.has(model)) {
            useBus(this.env.bus, this.agentLiveUpdate.EVENT, () => {
                this._scheduleReload();
            });
        }
    },

    onWillUnmount() {
        if (this._listReloadTimer) {
            clearTimeout(this._listReloadTimer);
            this._listReloadTimer = null;
        }
        return this._super(...arguments);
    },

    _scheduleReload() {
        if (this._listReloadTimer) return;
        this._listReloadTimer = setTimeout(async () => {
            this._listReloadTimer = null;
            const root = this.model && this.model.root;
            if (root && typeof root.load === "function") {
                try {
                    await root.load();
                } catch (_err) {
                    // If the load fails (e.g. user is editing a row) we just
                    // skip this cycle and wait for the next notification.
                }
            }
        }, RELOAD_DEBOUNCE_MS);
    },
});
