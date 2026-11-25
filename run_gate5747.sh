#!/usr/bin/env bash
set -uo pipefail
cd /tmp/gate5747
DB="gate5747b"
PG="pg_5747b"
NET="net_5747b"
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
cat > /tmp/gate5747/odoo.conf <<CONF
[options]
db_host = $PG
db_user = odoo
db_password = odoo
addons_path = /usr/lib/odoo/addons,/mnt/extra-addons
without_demo = False
CONF
ODOO_IMG="nra5703-odoo:18"
docker run --rm --network "$NET" \
  -v /tmp/gate5747:/mnt/extra-addons \
  -v /tmp/gate5747/odoo.conf:/etc/odoo/odoo.conf \
  "$ODOO_IMG" odoo -c /etc/odoo/odoo.conf \
  -d "$DB" -i mail_bot_odooclaw,hr --test-enable --test-tags "/mail_bot_odooclaw" \
  --stop-after-init > /tmp/gate5747/odoo_run.log 2>&1
echo "ODOO_RC=$?"
docker rm -f "$PG" >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true
