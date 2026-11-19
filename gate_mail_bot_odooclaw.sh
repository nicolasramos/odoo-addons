#!/usr/bin/env bash
# =============================================================================
# Gate: real install + tests of the mail_bot_odooclaw family on a clean
# Odoo 18 base, with anti-"empty green" guards.
#
# Four guards, ALL must hold for GREEN (exit 0):
#   Guard A (module loaded):   mail_bot_odooclaw is loaded during the run
#                              (odoo log: "Module mail_bot_odooclaw loaded").
#   Guard B (tests ran):       at least one test executes -> "of N tests", N > 0.
#   Guard C (no failures):     failed == 0 AND error(s) == 0 in the summary.
#   Guard D (odoo rc):         odoo exits 0 (--test-enable returns non-zero on a
#                              failing battery).
# A module that never loaded, a "0 failed ... of 0 tests" run, a run with any
# failed/error test, or a non-zero odoo rc is RED (exit 1). This is the point of
# the gate: the whole document-intake chain was mounted on staging; a bare
# "0 failed" with zero tests executed (or hidden failures) would have looked
# green while proving nothing. These four guards close that hole.
#
# Usage:
#   ./gate_mail_bot_odooclaw.sh [DB] [INSTALL_FLAG] [TEST_FILTER] [MODULE]
# Examples:
#   GREEN : ./gate_mail_bot_odooclaw.sh gate_db "-i mail_bot_odooclaw,hr" "/mail_bot_odooclaw"
#   RED-A : ./gate_mail_bot_odooclaw.sh g1 "-i hr"                              "/mail_bot_odooclaw"
#   RED-B : ./gate_mail_bot_odooclaw.sh g2 "-i mail_bot_odooclaw,hr"           "-at_install,-post_install"
#   Full family (companion modules): -i mail_bot_odooclaw,hr,mail_bot_odooclaw_expense,mail_bot_odooclaw_account
#
# Reproducible & self-contained: it spins up a dedicated postgres container and
# runs odoo:18.0 against a fresh DB, mounting the addons path (the repo root by
# default). Only prerequisites are docker and the odoo:18.0 image (both on
# staging/mini-7192). Nothing is committed to the DB (--stop-after-init).
# =============================================================================
set -uo pipefail

DB="${1:-gate_db}"
INSTALL_FLAG="${2:--i mail_bot_odooclaw,hr}"
TFILT="${3:-/mail_bot_odooclaw}"
MODULE="${4:-mail_bot_odooclaw}"
ODOO_IMG="${ODOO_IMG:-odoo:18.0}"
PG_IMG="${PG_IMG:-postgres:16}"

# Addons path defaults to the directory that holds this script (the addons repo
# root, where mail_bot_odooclaw/ lives). Override with ADDONS_PATH when the
# module lives elsewhere (e.g. a detached checkout).
ADDONS_PATH="${ADDONS_PATH:-$(cd "$(dirname "$0")" && pwd)}"
WORKDIR="$(mktemp -d /tmp/gate.XXXXXX)"
CONFIG="$WORKDIR/odoo.conf"
LOG="$WORKDIR/odoo_run.log"
# Derive container/network names from the DB so concurrent gates on different
# databases do not collide on fixed names (gate_pg/gate_net).
PG_CONTAINER="pg_$(echo "$DB" | tr -c '[:alnum:]_' '_')"
NETWORK="net_$(echo "$DB" | tr -c '[:alnum:]_' '_')"

cat > "$CONFIG" <<EOF
[options]
db_host = $PG_CONTAINER
db_user = odoo
db_password = odoo
addons_path = /usr/lib/odoo/addons,/mnt/extra-addons
without_demo = False
EOF
chmod 755 "$WORKDIR" 2>/dev/null || true
chmod 644 "$CONFIG"

cleanup() {
  docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

# Be forgiving of a previous run killed mid-flight (leftover net/containers).
docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
docker network rm "$NETWORK" >/dev/null 2>&1 || true

docker network create "$NETWORK"
docker run -d --name "$PG_CONTAINER" --network "$NETWORK" \
  -e POSTGRES_PASSWORD=odoo -e POSTGRES_USER=odoo -e POSTGRES_DB=postgres \
  "$PG_IMG"

for _ in $(seq 1 30); do
  docker exec "$PG_CONTAINER" pg_isready -U odoo -h 127.0.0.1 >/dev/null 2>&1 && break
  sleep 1
done

# Install + test. --stop-after-init initialises the module and runs the battery
# but does not commit, so guards read the LOG, not the committed DB state.
docker run --rm \
  --network "$NETWORK" \
  -v "$ADDONS_PATH:/mnt/extra-addons" \
  -v "$CONFIG:/etc/odoo/odoo.conf" \
  "$ODOO_IMG" odoo -c /etc/odoo/odoo.conf \
  -d "$DB" $INSTALL_FLAG --test-enable --test-tags "$TFILT" \
  --stop-after-init > "$LOG" 2>&1
ODOO_RC=$?

echo "==================== GATE SUMMARY ===================="

# Guard A: module loaded during this run.
if grep -qE "Module $MODULE loaded" "$LOG" 2>/dev/null; then
  MODULE_STATE="loaded"
else
  MODULE_STATE="absent"
fi
echo "Guard A -> module '$MODULE' loaded during run = ${MODULE_STATE:-<none>}"

# Guard B: tests actually executed.
TEST_SUMMARY="$(grep -oE "[0-9]+ failed, [0-9]+ error\(s\) of [0-9]+ tests" "$LOG" | tail -n 1)"
FAILED_COUNT="$(echo "$TEST_SUMMARY" | grep -oE "^[0-9]+ failed" | grep -oE "[0-9]+" | head -n 1)"
ERROR_COUNT="$(echo "$TEST_SUMMARY" | grep -oE "[0-9]+ error\(s\) of" | grep -oE "[0-9]+" | head -n 1)"
TEST_COUNT="$(echo "$TEST_SUMMARY" | grep -oE "of [0-9]+ tests" | grep -oE "[0-9]+" | head -n 1)"
echo "Guard B -> test summary = '${TEST_SUMMARY:-<none>}' (failed=${FAILED_COUNT:-?}, errors=${ERROR_COUNT:-?}, N=${TEST_COUNT:-0})"

# Verdict.
RED=0
[ "$MODULE_STATE" = "loaded" ] || { echo "Guard A: FAIL (module not loaded)"; RED=1; }
{ [ -n "${TEST_COUNT:-}" ] && [ "$TEST_COUNT" -gt 0 ]; } 2>/dev/null || { echo "Guard B: FAIL (no tests executed)"; RED=1; }
# Guard C: no failed tests and no errors. A summary like "2 failed, 0 error(s) of
# 114 tests" passes Guard B (N>0) but must be RED.
if [ -n "${FAILED_COUNT:-}" ] && [ "$FAILED_COUNT" -gt 0 ] 2>/dev/null; then
  echo "Guard C: FAIL (${FAILED_COUNT} test(s) failed)"; RED=1
elif [ -n "${ERROR_COUNT:-}" ] && [ "$ERROR_COUNT" -gt 0 ] 2>/dev/null; then
  echo "Guard C: FAIL (${ERROR_COUNT} error(s) during tests)"; RED=1
fi
# Guard D: odoo exits non-zero when the failing battery runs.
[ "$ODOO_RC" -eq 0 ] || { echo "Guard D: FAIL (odoo rc=$ODOO_RC)"; RED=1; }

echo "------------------------------------------------------"
if [ "$RED" -eq 0 ]; then
  echo "GATE: GREEN  ($TEST_SUMMARY, module loaded)"
else
  echo "GATE: RED    (odoo rc=$ODOO_RC)"
fi
echo "======================================================="
exit $RED
