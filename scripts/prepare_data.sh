#!/usr/bin/env bash
#
# Builds the Bakta reference database into /data. KBase runs this once per
# data-version at registration time (`entrypoint.sh init`):
#   - /data is mounted read-write only now; at app runtime it is read-only
#     (/kb/data/kb_bakta/<data-version> on the KBase side).
#   - KBase keeps the volume only if /data/__READY__ exists at the end.
#   - If /kb/data/kb_bakta/<data-version> already exists, this script is NOT
#     re-run, so bump `data-version` in kbase.yml whenever this script changes.
#
# Result: /data/db is a ready-to-use Bakta DB (with AMRFinderPlus DB set up),
# which the app passes to `bakta_proteins --db /data/db`.

set -euo pipefail

# full | light. If you change this, also change data-version in kbase.yml.
DB_TYPE="${BAKTA_DB_TYPE:-full}"

# Bakta DB v6.0 (2025-02-24), required by Bakta 1.10.x / 1.11.x
# https://doi.org/10.5281/zenodo.14916843
ZENODO_RECORD="14916843"

case "${DB_TYPE}" in
  full)  DB_NAME="db";       DB_MD5="4c1115e40abfa2b464ae5dd988bdd88e" ;;  # ~30 GB xz, ~84 GB extracted
  light) DB_NAME="db-light"; DB_MD5="4a6e059ded39e9c5537ef4137d2f5648" ;;  # ~1.3 GB xz, ~3.9 GB extracted
  *) echo "ERROR: BAKTA_DB_TYPE must be 'full' or 'light' (got '${DB_TYPE}')" >&2; exit 1 ;;
esac

DATA_DIR="/data"
READY_FILE="${DATA_DIR}/__READY__"
ARCHIVE_NAME="${DB_NAME}.tar.xz"
URL="https://zenodo.org/records/${ZENODO_RECORD}/files/${ARCHIVE_NAME}?download=1"
# Download onto the ref-data volume, not the container's /tmp (too small for the full DB).
DOWNLOAD_DIR="${DATA_DIR}/_download"
ARCHIVE="${DOWNLOAD_DIR}/${ARCHIVE_NAME}"
DB_PATH="${DATA_DIR}/${DB_NAME}"

# Make sure the Bakta conda env (bakta_db, amrfinder_update, curl) is on PATH.
export PATH="/opt/conda/bin:${PATH}"

echo "Bakta reference data: type=${DB_TYPE}, zenodo record=${ZENODO_RECORD}"
echo "Tools: bakta_db=$(command -v bakta_db || echo MISSING), amrfinder_update=$(command -v amrfinder_update || echo MISSING)"
command -v bakta_db >/dev/null || { echo "ERROR: bakta_db not found on PATH" >&2; exit 1; }

rm -f "${READY_FILE}"
mkdir -p "${DOWNLOAD_DIR}"

md5_of() { md5sum "$1" | cut -d' ' -f1; }

download() {
  if command -v curl >/dev/null; then
    curl -fL --retry 5 --retry-delay 15 --connect-timeout 60 -C - -o "${ARCHIVE}" "${URL}"
  else
    wget -c -T 120 -t 5 -O "${ARCHIVE}" "${URL}"
  fi
}

# Download (resuming partial files) and verify the checksum; retry a few times.
ok=0
for attempt in 1 2 3 4 5; do
  if [ -f "${ARCHIVE}" ] && [ "$(md5_of "${ARCHIVE}")" = "${DB_MD5}" ]; then
    ok=1; break
  fi
  echo "Downloading ${URL} (attempt ${attempt}/5)..."
  rc=0; download || rc=$?
  if [ "${rc}" -eq 0 ]; then
    actual="$(md5_of "${ARCHIVE}")"
    if [ "${actual}" = "${DB_MD5}" ]; then ok=1; break; fi
    echo "MD5 mismatch (expected ${DB_MD5}, got ${actual}); discarding archive."
    rm -f "${ARCHIVE}"
  else
    echo "Download failed with exit code ${rc}."
    # 33 = server refused byte-range resume; start over next time.
    [ "${rc}" -eq 33 ] && rm -f "${ARCHIVE}"
  fi
  sleep 30
done
[ "${ok}" -eq 1 ] || { echo "ERROR: could not download a valid ${ARCHIVE_NAME} from Zenodo" >&2; exit 1; }
echo "Archive OK: ${ARCHIVE} (md5 ${DB_MD5})"

# Extract, check the DB schema version and set up the AMRFinderPlus DB
# (creates ${DB_PATH}/amrfinderplus-db/latest, which bakta_proteins needs).
rm -rf "${DB_PATH}"
bakta_db install --db-file "${ARCHIVE}" --output "${DATA_DIR}"

# The app always uses /data/db.
if [ "${DB_NAME}" != "db" ]; then
  ln -sfn "${DB_NAME}" "${DATA_DIR}/db"
fi

# Sanity checks before marking the volume ready.
for f in version.json amrfinderplus-db/latest; do
  [ -e "${DATA_DIR}/db/${f}" ] || { echo "ERROR: ${DATA_DIR}/db/${f} missing after install" >&2; exit 1; }
done
cat "${DATA_DIR}/db/version.json"; echo

rm -rf "${DOWNLOAD_DIR}"
du -sh "${DB_PATH}" || true

touch "${READY_FILE}"
echo "Reference data successfully prepared. READY file created."
