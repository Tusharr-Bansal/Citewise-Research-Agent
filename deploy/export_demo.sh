#!/usr/bin/env bash
# Export the demo project (only) as a data-only SQL dump: deploy/demo_data.sql.gz.
# The app creates the schema itself and loads this file on first start against an empty database.
# Usage: deploy/export_demo.sh   (reads DATABASE_URL, default: local dev database)
set -euo pipefail
SRC="${DATABASE_URL:-postgresql://pcg:pcg@localhost:5432/citewise}"
OUT="$(cd "$(dirname "$0")" && pwd)/demo_data.sql.gz"
TMPDB="citewise_export_$$"
ADMIN="${SRC%/*}/postgres"

psql "$ADMIN" -qc "CREATE DATABASE $TMPDB" >/dev/null
trap 'psql "$ADMIN" -qc "DROP DATABASE IF EXISTS $TMPDB" >/dev/null' EXIT
pg_dump "$SRC" --no-owner --no-acl | psql "${SRC%/*}/$TMPDB" -q >/dev/null 2>&1 || true
psql "${SRC%/*}/$TMPDB" -qc "DELETE FROM projects WHERE NOT is_demo"
# Refuse to overwrite a good dump with a broken one: the copy must actually contain the demo's passages.
# (Once, the temporary database failed to create silently, e.g. CREATE EXTENSION vector needs a
# superuser, and a 4 KB dump with no chunks replaced the real one.)
CHUNKS=$(psql "${SRC%/*}/$TMPDB" -Atc "SELECT count(*) FROM chunks" 2>/dev/null || echo 0)
if [ "${CHUNKS:-0}" -lt 100 ]; then
  echo "ERROR: export copy has ${CHUNKS:-0} chunks; refusing to write $OUT (run as a role that can CREATE EXTENSION vector)" >&2
  exit 1
fi
pg_dump "${SRC%/*}/$TMPDB" --data-only --no-owner --no-acl -t projects -t papers -t chunks | gzip -9 > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1)):"
psql "${SRC%/*}/$TMPDB" -Atc "SELECT 'projects', count(*) FROM projects UNION ALL SELECT 'papers', count(*) FROM papers UNION ALL SELECT 'chunks', count(*) FROM chunks"
