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

export const AGENT_NOTIFICATION_TYPE = "odoo_agent";
const EXECUTION_CHANNEL_PREFIX = "odoo_agent.execution.";
const AGENT_CHANNEL_PREFIX = "odoo_agent.agent.";
const TASK_CHANNEL_PREFIX = "odoo_agent.project_task.";

const ODOO_AGENT_EVENT = "odoo_agent:notification";

function channelsFor({ executionId, agentId, projectTaskId }) {
    const channels = [];
    if (executionId) {
        channels.push(EXECUTION_CHANNEL_PREFIX + executionId);
    }
    if (agentId) {
        channels.push(AGENT_CHANNEL_PREFIX + agentId);
    }
    if (projectTaskId) {
        channels.push(TASK_CHANNEL_PREFIX + projectTaskId);
    }
    return channels;
}

export const agentLiveUpdateService = {
    dependencies: ["bus_service"],
    start(env, { bus_service }) {
        const subscribed = new Set();

        function watchRecord(ids) {
            for (const channel of channelsFor(ids)) {
                if (subscribed.has(channel)) {
                    continue;
                }
                bus_service.addChannel(channel);
                subscribed.add(channel);
            }
        }

        function unwatchRecord(ids) {
            for (const channel of channelsFor(ids)) {
                if (!subscribed.has(channel)) {
                    continue;
                }
                bus_service.deleteChannel(channel);
                subscribed.delete(channel);
            }
        }

        // Since Odoo 17 the bus dispatches notifications per type; there is
        // no generic "notification" event anymore.
        bus_service.subscribe(AGENT_NOTIFICATION_TYPE, (payload) => {
            env.bus.trigger(ODOO_AGENT_EVENT, payload || {});
        });

        return {
            watchRecord,
            unwatchRecord,
            EVENT: ODOO_AGENT_EVENT,
            _subscribed: subscribed,
        };
    },
};

registry.category("services").add("agent_live_update", agentLiveUpdateService);
