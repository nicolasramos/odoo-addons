/** @odoo-module **/

/**
 * Live update for the form view of odoo_agent models.
 *
 * The patch is intentionally narrow:
 *
 *   1. When a record is loaded, ask ``agent_live_update`` to subscribe to
 *      its execution / agent / project_task channels.
 *   2. When the ``odoo_agent:notification`` event fires, decide whether
 *      the payload refers to the record currently on screen; if it does,
 *      re-fetch the record so the user sees the new state without
 *      manually reloading the page.
 *   3. When the user navigates to another record (or closes the form),
 *      unwatch the old one to keep the websocket subscription tight.
 *
 * Models covered:
 *   - odoo.agent.execution
 *   - odoo.agent.agent
 *   - odoo.agent.runtime
 *   - odoo.agent.chat
 *   - project.task  (only when an agent_id is set, to keep cost down)
 *
 * Why the ``load`` re-fetch rather than a field-level patch?
 * ---------------------------------------------------------
 * The backend can mutate more fields than we can sensibly patch client
 * side (status, started_at, completed_at, log_count, deliverability,
 * etc.). A ``model.root.load()`` is one round trip and is guaranteed to
 * show the new state. We throttle it (see ``_shouldReload``) so a
 * burst of notifications does not produce a thundering herd of
 * requests.
 */

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { useBus } from "@web/core/utils/hooks";
import { useService } from "@web/core/utils/hooks";
import { onWillUnmount } from "@odoo/owl";

const AGENT_MODELS = new Set([
    "odoo.agent.execution",
    "odoo.agent.agent",
    "odoo.agent.runtime",
    "odoo.agent.chat",
]);

const RELOAD_DEBOUNCE_MS = 400;

function pickIds(record) {
    if (!record || !record.resId) return null;
    const data = record.data || {};
    return {
        executionId: data.id,
        agentId: data.agent_id && data.agent_id[0],
        projectTaskId: data.task_id && data.task_id[0],
    };
}

function pickIdsForProjectTask(record) {
    if (!record || !record.resId) return null;
    const data = record.data || {};
    return {
        agentId: data.agent_id && data.agent_id[0],
        projectTaskId: data.id,
    };
}

export const AgentFormLiveUpdate = {
    dependencies: [...FormController.dependencies, "agent_live_update"],
};

patch(FormController.prototype, {
    setup() {
        this._super(...arguments);
        this.agentLiveUpdate = useService("agent_live_update");
        this._reloadTimer = null;
        this._watchedKey = null;

        const model = this.props && this.props.resModel;
        if (AGENT_MODELS.has(model) || model === "project.task") {
            useBus(this.env.bus, this.agentLiveUpdate.EVENT, (ev) => {
                this._onAgentNotification(ev.detail);
            });
        }
    },

    /**
     * Subscribe to the bus channels for the new record as soon as it is
     * known which record the form is showing.
     */
    async onRecordChanged(record) {
        await this._super(...arguments);
        const ids = this._extractIds(record);
        if (!ids) {
            this._unwatchCurrent();
            return;
        }
        const key = JSON.stringify(ids);
        if (key === this._watchedKey) return;
        this._unwatchCurrent();
        this._watchedKey = key;
        this.agentLiveUpdate.watchRecord(ids);
    },

    onWillUnmount() {
        this._unwatchCurrent();
        if (this._reloadTimer) {
            clearTimeout(this._reloadTimer);
            this._reloadTimer = null;
        }
        return this._super(...arguments);
    },

    _extractIds(record) {
        const model = this.props && this.props.resModel;
        if (AGENT_MODELS.has(model)) {
            return pickIds(record);
        }
        if (model === "project.task") {
            return pickIdsForProjectTask(record);
        }
        return null;
    },

    _unwatchCurrent() {
        if (!this._watchedKey) return;
        try {
            const ids = JSON.parse(this._watchedKey);
            this.agentLiveUpdate.unwatchRecord(ids);
        } catch (_err) {
            // _watchedKey is always JSON we produced; ignore parse errors.
        }
        this._watchedKey = null;
    },

    _onAgentNotification(payload) {
        const record = this.model && this.model.root;
        if (!record || !record.resId) return;
        if (!this._payloadTargetsCurrentRecord(payload, record)) return;
        this._scheduleReload();
    },

    _payloadTargetsCurrentRecord(payload, record) {
        if (!payload) return false;
        const data = record.data || {};
        if (payload.execution_id && data.id === payload.execution_id) return true;
        if (payload.agent_id) {
            const agentId = data.agent_id && data.agent_id[0];
            if (agentId === payload.agent_id) return true;
        }
        if (payload.task_id) {
            const taskId = data.task_id && data.task_id[0];
            if (taskId === payload.task_id) return true;
        }
        return false;
    },

    _scheduleReload() {
        if (this._reloadTimer) return;
        this._reloadTimer = setTimeout(() => {
            this._reloadTimer = null;
            const record = this.model && this.model.root;
            if (record && typeof record.load === "function") {
                record.load();
            }
        }, RELOAD_DEBOUNCE_MS);
    },
});
