# End-to-end tests

Browser tests against a live Odoo with the engine running. They are skipped
unless `ODOO_E2E_URL`, `ODOO_E2E_LOGIN` and `ODOO_E2E_PASSWORD` are set, so the
normal unit suite never depends on a staging server.

They need Playwright and a Chrome install:

    NODE_PATH=/Users/nramos/node_modules \
    ODOO_E2E_URL=http://192.168.1.21:18083 ODOO_E2E_DB=forge_preview_live \
    ODOO_E2E_LOGIN=odooclaw ODOO_E2E_PASSWORD=... \
    node tests/e2e/odooclaw_chatter.cjs

What they prove:

- A comment written in the chatter becomes an internal note authored by
  OdooClaw within three minutes.
- An invoice photo attached to the message is read before the answer: the note
  talks about the invoice, not about a message with no content.
