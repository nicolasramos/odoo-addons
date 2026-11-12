/**
 * Hoot tests for ``agent_live_update`` service.
 *
 * These tests do not need a real Odoo bus_service -- we hand-roll a stub
 * that records the channels the service subscribes to and lets us fire
 * synthetic notifications by type. The test asserts:
 *
 *   1. ``watchRecord`` subscribes to the three channel families.
 *   2. ``watchRecord`` is idempotent: calling it twice does not re-add
 *      the same channel.
 *   3. ``unwatchRecord`` drops the channels.
 *   4. A backend ``odoo_agent`` notification triggers the
 *      ``odoo_agent:notification`` event on ``env.bus`` with the payload.
 *   5. Notifications of other types are ignored.
 */

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";

import { agentLiveUpdateService } from "@odoo_agent/js/agent_live_update_service";

function makeBusServiceStub() {
    const channels = new Set();
    const subscribers = new Map();
    return {
        channels,
        addChannel(name) {
            channels.add(name);
        },
        deleteChannel(name) {
            channels.delete(name);
        },
        subscribe(type, callback) {
            if (!subscribers.has(type)) {
                subscribers.set(type, []);
            }
            subscribers.get(type).push(callback);
        },
        _fire(type, payload) {
            for (const callback of subscribers.get(type) || []) {
                callback(payload, { id: 1 });
            }
        },
    };
}

function startService() {
    const bus_service = makeBusServiceStub();
    const env = { bus: new EventBus() };
    const service = agentLiveUpdateService.start(env, { bus_service });
    return { bus_service, env, service };
}

describe.current.tags("headless");

describe("agent_live_update service", () => {
    test("watchRecord subscribes to the three channel families", () => {
        const { bus_service, service } = startService();
        service.watchRecord({ executionId: 7, agentId: 12, projectTaskId: 5 });
        expect(bus_service.channels.has("odoo_agent.execution.7")).toBe(true);
        expect(bus_service.channels.has("odoo_agent.agent.12")).toBe(true);
        expect(bus_service.channels.has("odoo_agent.project_task.5")).toBe(true);
    });

    test("watchRecord is idempotent", () => {
        const { bus_service, service } = startService();
        let adds = 0;
        const original = bus_service.addChannel.bind(bus_service);
        bus_service.addChannel = (name) => {
            adds += 1;
            original(name);
        };
        service.watchRecord({ executionId: 7, agentId: 12 });
        service.watchRecord({ executionId: 7, agentId: 12 });
        expect(adds).toBe(2);
    });

    test("unwatchRecord drops the channels", () => {
        const { bus_service, service } = startService();
        service.watchRecord({ executionId: 7, agentId: 12, projectTaskId: 5 });
        service.unwatchRecord({ executionId: 7, agentId: 12, projectTaskId: 5 });
        expect(bus_service.channels.size).toBe(0);
    });

    test("odoo_agent notification triggers local event", () => {
        const { bus_service, env, service } = startService();
        const received = [];
        env.bus.addEventListener(service.EVENT, (ev) => received.push(ev.detail));
        bus_service._fire("odoo_agent", { event: "execution_updated", execution_id: 7 });
        expect(received).toEqual([{ event: "execution_updated", execution_id: 7 }]);
    });

    test("non odoo_agent notifications are filtered out", () => {
        const { bus_service, env, service } = startService();
        const received = [];
        env.bus.addEventListener(service.EVENT, (ev) => received.push(ev.detail));
        bus_service._fire("some_other_module", { x: 1 });
        expect(received.length).toBe(0);
    });
});
