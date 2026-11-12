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
 *   - odoo.agent
 *   - project.task
 *
 * Why the ``load`` re-fetch rather than a field-level patch?
 * ---------------------------------------------------------
 * The backend can mutate more fields than we can sensibly patch client
 * side (status, started_at, completed_at, log_count, deliverability,
 * etc.). A ``model.root.load()`` is one round trip and is guaranteed to
 * show the new state. We debounce it (see ``_scheduleReload``) so a
 * burst of notifications does not produce a thundering herd of
 * requests.
 */

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { useBus, useService } from "@web/core/utils/hooks";
import { onWillUnmount } from "@odoo/owl";

const RELOAD_DEBOUNCE_MS = 400;

/** Many2one values are ``{ id, display_name }`` objects (or false). */
function m2oId(value) {
    return (value && value.id) || false;
}

/** Map a form record to the bus channel ids it should listen to. */
const ID_EXTRACTORS = {
    "odoo.agent.execution": (data) => ({
        executionId: data.id,
        agentId: m2oId(data.agent_id),
        projectTaskId: m2oId(data.task_id),
    }),
    "odoo.agent": (data) => ({
        agentId: data.id,
    }),
    "project.task": (data) => ({
        agentId: m2oId(data.agent_id),
        projectTaskId: data.id,
    }),
};

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        const extractor = ID_EXTRACTORS[this.props.resModel];
        if (!extractor) {
            return;
        }
        this.agentLiveUpdate = useService("agent_live_update");
        this._agentExtractIds = extractor;
        this._agentReloadTimer = null;
        this._agentWatchedKey = null;

        useBus(this.env.bus, this.agentLiveUpdate.EVENT, (ev) => {
            this._onAgentNotification(ev.detail);
        });
        onWillUnmount(() => {
            this._agentUnwatchCurrent();
            if (this._agentReloadTimer) {
                clearTimeout(this._agentReloadTimer);
                this._agentReloadTimer = null;
            }
        });
    },

    /**
     * Subscribe to the bus channels of the record once it is (re)loaded,
     * e.g. on first display or when navigating with the pager.
     */
    async onRootLoaded() {
        await super.onRootLoaded(...arguments);
        if (this._agentExtractIds) {
            this._agentWatch(this.model.root);
        }
    },

    _agentWatch(record) {
        if (!record || !record.resId) {
            this._agentUnwatchCurrent();
            return;
        }
        const ids = this._agentExtractIds(record.data || {});
        const key = JSON.stringify(ids);
        if (key === this._agentWatchedKey) {
            return;
        }
        this._agentUnwatchCurrent();
        this._agentWatchedKey = key;
        this.agentLiveUpdate.watchRecord(ids);
    },

    _agentUnwatchCurrent() {
        if (!this._agentWatchedKey) {
            return;
        }
        this.agentLiveUpdate.unwatchRecord(JSON.parse(this._agentWatchedKey));
        this._agentWatchedKey = null;
    },

    _onAgentNotification(payload) {
        const record = this.model.root;
        if (!record || !record.resId || !payload) {
            return;
        }
        const ids = this._agentExtractIds(record.data || {});
        const matches =
            (payload.execution_id && payload.execution_id === ids.executionId) ||
            (payload.agent_id && payload.agent_id === ids.agentId) ||
            (payload.task_id && payload.task_id === ids.projectTaskId) ||
            (payload.project_task_id && payload.project_task_id === ids.projectTaskId);
        if (matches) {
            this._scheduleAgentReload();
        }
    },

    _scheduleAgentReload() {
        if (this._agentReloadTimer) {
            return;
        }
        this._agentReloadTimer = setTimeout(async () => {
            this._agentReloadTimer = null;
            const record = this.model.root;
            // Never clobber the user's unsaved edits.
            if (record && !(await record.isDirty())) {
                await record.load();
            }
        }, RELOAD_DEBOUNCE_MS);
    },
});
