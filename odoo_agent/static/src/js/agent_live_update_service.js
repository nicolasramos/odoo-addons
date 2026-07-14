/** @odoo-module **/

/**
 * Live update client for the odoo_agent addon.
 *
 * The backend (bus.bus) publishes three families of channels when agent
 * executions, logs or chat messages change:
 *
 *   - "odoo_agent.execution.{id}"
 *   - "odoo_agent.agent.{id}"
 *   - "odoo_agent.project_task.{id}"
 *
 * Notifications carry type = "odoo_agent" and a payload that includes an
 * "event" field (execution_updated, log_created, chat_message_created).
 * The client here is responsible for:
 *
 *   1. subscribing to the relevant channels for the records currently on
 *      screen (form view, list view, embedded chatter);
 *   2. broadcasting the incoming payload on env.bus so other components
 *      (form controller, list controller, custom widgets) can react
 *      without re-subscribing to the network bus.
 *
 * It does NOT touch the DOM directly. That keeps the contract small and
 * makes the unit test trivial.
 */

import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";

const AGENT_NOTIFICATION_TYPE = "odoo_agent";
const EXECUTION_CHANNEL_PREFIX = "odoo_agent.execution.";
const AGENT_CHANNEL_PREFIX = "odoo_agent.agent.";
const TASK_CHANNEL_PREFIX = "odoo_agent.project_task.";

const ODOO_AGENT_EVENT = "odoo_agent:notification";

function summarise(notifications) {
    const out = [];
    for (const note of notifications) {
        if (!note || note.type !== AGENT_NOTIFICATION_TYPE) {
            continue;
        }
        out.push(note.payload || {});
    }
    return out;
}

export const agentLiveUpdateService = {
    dependencies: ["bus_service"],
    start(env, { bus_service }) {
        const subscribed = new Set();
        const pending = new Deferred();

        function watchRecord({ executionId, agentId, projectTaskId }) {
            const candidates = [];
            if (executionId) candidates.push(EXECUTION_CHANNEL_PREFIX + executionId);
            if (agentId) candidates.push(AGENT_CHANNEL_PREFIX + agentId);
            if (projectTaskId) candidates.push(TASK_CHANNEL_PREFIX + projectTaskId);
            for (const channel of candidates) {
                if (subscribed.has(channel)) continue;
                bus_service.addChannel(channel);
                subscribed.add(channel);
            }
        }

        function unwatchRecord({ executionId, agentId, projectTaskId }) {
            const drop = new Set();
            if (executionId) drop.add(EXECUTION_CHANNEL_PREFIX + executionId);
            if (agentId) drop.add(AGENT_CHANNEL_PREFIX + agentId);
            if (projectTaskId) drop.add(TASK_CHANNEL_PREFIX + projectTaskId);
            for (const channel of drop) {
                if (!subscribed.has(channel)) continue;
                if (typeof bus_service.removeChannel === "function") {
                    bus_service.removeChannel(channel);
                }
                subscribed.delete(channel);
            }
        }

        bus_service.addEventListener("notification", ({ detail }) => {
            const payloads = summarise(Array.isArray(detail) ? detail : [detail]);
            if (!payloads.length) return;
            for (const payload of payloads) {
                env.bus.trigger(ODOO_AGENT_EVENT, payload);
            }
        });

        if (typeof bus_service.start === "function") {
            bus_service.start();
        }
        pending.resolve();

        return {
            watchRecord,
            unwatchRecord,
            EVENT: ODOO_AGENT_EVENT,
            ready: pending,
            _subscribed: subscribed,
        };
    },
};

registry.category("services").add("agent_live_update", agentLiveUpdateService);
