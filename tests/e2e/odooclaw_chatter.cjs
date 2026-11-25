// End-to-end proof of the chatter pipeline against a live Odoo.
//
// Drives the real web client with Playwright: login, open the ticket, open the
// chatter composer, write, send. The assertions read the messages and the run
// through the same session, because the chatter groups authors and an internal
// note is not labelled per message in the DOM.
//
//   NODE_PATH=/Users/nramos/node_modules \
//   ODOO_E2E_URL=http://192.168.1.21:18083 ODOO_E2E_DB=forge_preview_live \
//   ODOO_E2E_LOGIN=admin ODOO_E2E_PASSWORD=... \
//   node tests/e2e/odooclaw_chatter.cjs
const assert = require('assert');
const path = require('path');
const { chromium } = require('playwright');

const URL = process.env.ODOO_E2E_URL;
const DB = process.env.ODOO_E2E_DB || 'forge_preview_live';
const LOGIN = process.env.ODOO_E2E_LOGIN;
const PASSWORD = process.env.ODOO_E2E_PASSWORD;
const TICKET = Number(process.env.ODOO_E2E_TICKET || 5);

if (!URL || !LOGIN || !PASSWORD) {
  console.log('SKIP: ODOO_E2E_URL, ODOO_E2E_LOGIN and ODOO_E2E_PASSWORD are required');
  process.exit(0);
}

async function rpc(page, model, method, kwargs) {
  const res = await page.request.post(`${URL}/web/dataset/call_kw/${model}/${method}`, {
    data: { jsonrpc: '2.0', method: 'call', params: { model, method, args: [], kwargs } },
  });
  const body = await res.json();
  if (body.error) throw new Error((body.error.data && body.error.data.message) || 'rpc error');
  return body.result;
}

async function newestTicketMessage(page) {
  const result = await rpc(page, 'mail.message', 'web_search_read', {
    domain: [['model', '=', 'helpdesk.ticket'], ['res_id', '=', TICKET]],
    specification: { id: {}, body: {}, author_id: {} },
    limit: 1,
    order: 'id desc',
  });
  const rows = (result && result.records) || [];
  assert(rows.length, 'the ticket has no messages');
  return rows[0];
}

async function waitForRun(page, messageId, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await rpc(page, 'mail.odooclaw.pipeline.run', 'web_search_read', {
      domain: [['message_id', '=', messageId]],
      specification: { id: {}, state: {}, decision: {} },
      limit: 1,
      order: 'id desc',
    });
    const rows = (result && result.records) || [];
    if (rows.length && rows[0].state !== 'queued') return rows[0];
    await page.waitForTimeout(5000);
  }
  throw new Error(`no run finished for message ${messageId}`);
}

async function openTicket(page) {
  await page.goto(`${URL}/web/login?db=${DB}`);
  await page.fill('input[name="login"]', LOGIN);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => u.pathname.startsWith('/odoo'), { timeout: 30000 });
  await page.goto(`${URL}/odoo/helpdesk.ticket/${TICKET}`);
  await page.waitForSelector('.o-mail-Chatter-sendMessage', { timeout: 20000 });
  // A chat window from an earlier session can hold the first composer in the
  // DOM; close it so the chatter is the only target.
  const closes = page.locator('.o-mail-ChatWindow .o-mail-ChatWindow-close');
  for (let i = await closes.count(); i > 0; i--) {
    await closes.first().click().catch(() => {});
    await page.waitForTimeout(200);
  }
  // The chatter keeps the composer closed behind "Send message" until asked.
  await page.locator('.o-mail-Chatter-sendMessage').click();
  await page.waitForSelector('.o-mail-Chatter .o-mail-Composer-input', { timeout: 10000 });
}

async function send(page, text) {
  const input = page.locator('.o-mail-Chatter .o-mail-Composer-input');
  await input.click();
  await page.keyboard.type(text, { delay: 5 });
  await page.waitForTimeout(400);
  await page.locator('.o-mail-Chatter .o-mail-Composer-send').click();
  await page.waitForTimeout(3000);
}

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  try {
    await openTicket(page);
    await send(page, `E2E ${Date.now()} quiero saber el estado de mi pedido`);
    const message = await newestTicketMessage(page);
    assert(/quiero saber el estado/i.test(message.body), 'the comment was not posted in the ticket');
    const run = await waitForRun(page, message.id);
    assert(['drafted', 'sent', 'escalated'].includes(run.state), `unexpected run state ${run.state}`);
    assert(run.decision && run.decision.length > 10, 'the run has no decision');
    console.log(`PASS text: message ${message.id} -> run ${run.id} ${run.state} -> ${run.decision.slice(0, 140)}`);

    await openTicket(page);
    const fileInput = page.locator('.o-mail-Chatter .o-mail-Composer input[type="file"]');
    await fileInput.setInputFiles(path.join(__dirname, 'fixtures', 'factura.png'));
    await page.waitForTimeout(1500);
    await send(page, `E2E ${Date.now()} os adjunto la factura`);
    const imageMessage = await newestTicketMessage(page);
    const imageRun = await waitForRun(page, imageMessage.id);
    assert(imageRun.state !== 'failed', `the image run failed: ${imageRun.decision}`);
    assert(
      /factura|adjunt|documento|invoice|proveedor|acme/i.test(imageRun.decision || ''),
      `the model did not read the invoice: ${imageRun.decision}`
    );
    console.log(`PASS image: message ${imageMessage.id} -> run ${imageRun.id} ${imageRun.state} -> ${imageRun.decision.slice(0, 140)}`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error('FAIL', error.message); process.exit(1); });
