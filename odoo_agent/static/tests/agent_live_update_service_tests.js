/** @odoo-module **/

/**
 * Hoot tests for ``agent_live_update`` service.
 *
 * These tests do not need a real Odoo bus_service -- we hand-roll a stub
 * that records the channels the service subscribes to and lets us fire
 * synthetic ``notification`` events. The test asserts:
 *
 *   1. ``watchRecord`` subscribes to the three channel families.
 *   2. ``watchRecord`` is idempotent: calling it twice does not re-add
 *      the same channel.
 *   3. ``unwatchRecord`` drops the channels.
 *   4. A backend ``odoo_agent`` notification triggers the
 *      ``odoo_agent:notification`` event on ``env.bus`` with the
 *      backend payload.
 *   5. Non-odoo_agent notifications are filtered out.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeTestEnv } from "@web/../tests/web_test_helpers";
import { Deferred } from "@web/core/utils/concurrency";

import { agentLiveUpdateService } from "@agent_agent/static/src/js/agent_live_update_service.js";

function makeBusServiceStub() {
    const channels = new Set();
    const listeners = new Map();
    return {
        channels,
        addChannel(name) { channels.add(name); },
        removeChannel(name) { channels.delete(name); },
        start() {},
        addEventListener(name, cb) {
            if (!listeners.has(name)) listeners.set(name, []);
            listeners.get(name).push(cb);
        },
        removeEventListener(name, cb) {
            const list = listeners.get(name) || [];
            const idx = list.indexOf(cb);
            if (idx >= 0) list.splice(idx, 1);
        },
        _fire(name, detail) {
            for (const cb of listeners.get(name) || []) {
                cb({ detail });
            }
        },
    };
}

describe("agent_live_update service", () => {
    test("watchRecord subscribes to the three channel families", async () => {
        const bus_service = makeBusServiceStub();
        const env = await makeTestEnv({ services: { bus_service: { start: () => bus_service } } });
        const service = agentLiveUpdateService.start(env, { bus_service, orm: {} });
        service.watchRecord({ executionId: 7, agentId: 12, projectTaskId: 5 });
        expect(bus_service.channels.has("odoo_agent.execution.7")).toBe(true);
        expect(bus_service.channels.has("odoo_agent.agent.12")).toBe(true);
        expect(bus_service.channels.has("odoo_agent.project_task.5")).toBe(true);
    });

    test("watchRecord is idempotent", async () => {
        const bus_service = makeBusServiceStub();
        let adds = 0;
        const original = bus_service.addChannel.bind(bus_service);
        bus_service.addChannel = (name) => { adds += 1; original(name); };
        const env = await makeTestEnv({ services: { bus_service: { start: () => bus_service } } });
        const service = agentLiveUpdateService.start(env, { bus_service, orm: {} });
        service.watchRecord({ executionId: 7, agentId: 12 });
        service.watchRecord({ executionId: 7, agentId: 12 });
        expect(adds).toBe(2);
    });

    test("unwatchRecord drops the channels", async () => {
        const bus_service = makeBusServiceStub();
        const env = await makeTestEnv({ services: { bus_service: { start: () => bus_service } } });
        const service = agentLiveUpdateService.start(env, { bus_service, orm: {} });
        service.watchRecord({ executionId: 7, agentId: 12, projectTaskId: 5 });
        service.unwatchRecord({ executionId: 7, agentId: 12, projectTaskId: 5 });
        expect(bus_service.channels.size).toBe(0);
    });

    test("odoo_agent notification triggers local event", async () => {
        const bus_service = makeBusServiceStub();
        const env = await makeTestEnv({ services: { bus_service: { start: () => bus_service } } });
        const service = agentLiveUpdateService.start(env, { bus_service, orm: {} });
        const received = [];
        env.bus.addEventListener(service.EVENT, (ev) => received.push(ev.detail));
        bus_service._fire("notification", [{
            type: "odoo_agent",
            payload: { event: "execution_updated", execution_id: 7 },
        }]);
        expect(received).toEqual([{ event: "execution_updated", execution_id: 7 }]);
    });

    test("non odoo_agent notifications are filtered out", async () => {
        const bus_service = makeBusServiceStub();
        const env = await makeTestEnv({ services: { bus_service: { start: () => bus_service } } });
        const service = agentLiveUpdateService.start(env, { bus_service, orm: {} });
        const received = [];
        env.bus.addEventListener(service.EVENT, (ev) => received.push(ev.detail));
        bus_service._fire("notification", [{ type: "some_other_module", payload: { x: 1 } }]);
        expect(received.length).toBe(0);
    });
});
