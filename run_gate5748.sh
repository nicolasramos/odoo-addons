#!/usr/bin/env bash
set -uo pipefail
rm -rf /tmp/gate5748
git clone --depth 1 --branch feat/NRA-5747-mailbox-gateway-fix https://github.com/nicolasramos/odoo-addons.git /tmp/gate5748 >/tmp/clone5748.log 2>&1
cd /tmp/gate5748
echo "HEAD=$(git rev-parse --short HEAD)"
DB="gate5748"
PG="pg_5748"
NET="net_5748"
docker rm -f "$PG" >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true
docker network create "$NET"
docker run -d --name "$PG" --network "$NET" \
  -e POSTGRES_PASSWORD=odoo -e POSTGRES_USER=odoo -e POSTGRES_DB=postgres \
  postgres:16 >/dev/null
for _ in $(seq 1 30); do
  docker exec "$PG" pg_isready -U odoo -h 127.0.0.1 >/dev/null 2>&1 && break
  sleep 1
done
cat > /tmp/gate5748/odoo.conf <<CONF
[options]
db_host = $PG
db_user = odoo
db_password = odoo
addons_path = /usr/lib/odoo/addons,/mnt/extra-addons
without_demo = False
CONF
ODOO_IMG="nra5703-odoo:18"
docker run --rm --network "$NET" \
  -v /tmp/gate5748:/mnt/extra-addons \
  -v /tmp/gate5748/odoo.conf:/etc/odoo/odoo.conf \
  "$ODOO_IMG" odoo -c /etc/odoo/odoo.conf \
  -d "$DB" -i mail_bot_odooclaw,hr --test-enable --test-tags "/mail_bot_odooclaw" \
  --stop-after-init > /tmp/gate5748/odoo_run.log 2>&1
echo "ODOO_RC=$?"
docker rm -f "$PG" >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true
echo "=== SUMMARY ==="
grep -oE "[0-9]+ failed, [0-9]+ error\(s\) of [0-9]+ tests" /tmp/gate5748/odoo_run.log | tail -1
echo "=== gateway test results ==="
grep -nE "test_mailbox_gateway|MailboxGateway\.|ok$|ERROR: setUpClass" /tmp/gate5748/odoo_run.log | head -30
