/**
 * Live update for the list view of odoo_agent models.
 *
 * The list controller does not know about individual records, so it cannot
 * re-fetch a single row cheaply. Instead, when an ``odoo_agent:notification``
 * arrives, we ask the list model to reload the rows that are currently
 * on screen. Odoo's relational model will only re-read the records that
 * are actually being displayed, so the cost stays bounded.
 *
 * The patch is opt-in: only the execution, log and chat message lists are
 * covered, because those are the lists where live updates matter (you watch
 * executions finish, you watch logs stream in). Other models are skipped to
 * keep the websocket quiet.
 *
 * Note: notifications are only received for channels some other component
 * (typically an open form) subscribed to through ``agent_live_update``.
 */

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";
import { useBus, useService } from "@web/core/utils/hooks";
import { onWillUnmount } from "@odoo/owl";

const AGENT_LIST_MODELS = new Set([
    "odoo.agent.execution",
    "odoo.agent.log",
    "odoo.agent.chat.message",
]);

const RELOAD_DEBOUNCE_MS = 800;

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        if (!AGENT_LIST_MODELS.has(this.props.resModel)) {
            return;
        }
        this.agentLiveUpdate = useService("agent_live_update");
        this._agentListReloadTimer = null;
        useBus(this.env.bus, this.agentLiveUpdate.EVENT, () => {
            this._scheduleAgentListReload();
        });
        onWillUnmount(() => {
            if (this._agentListReloadTimer) {
                clearTimeout(this._agentListReloadTimer);
                this._agentListReloadTimer = null;
            }
        });
    },

    _scheduleAgentListReload() {
        if (this._agentListReloadTimer) {
            return;
        }
        this._agentListReloadTimer = setTimeout(async () => {
            this._agentListReloadTimer = null;
            const root = this.model.root;
            // Skip the cycle while a row is being edited.
            if (!root || root.editedRecord) {
                return;
            }
            try {
                await root.load();
            } catch {
                // Wait for the next notification.
            }
        }, RELOAD_DEBOUNCE_MS);
    },
});
