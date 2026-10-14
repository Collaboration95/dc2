#!/bin/sh
# Install /opt/dc2 from a reviewed artifact; secrets are private operator injection.
set -eu
umask 077
# Future installation must inject both dispositions into root-owned mount.env.
[ "${DC2_STATE_INSTALL_APPROVED:-false}" = true ] || exit 1
[ "${DC2_ORIGIN_HTTP_ACCEPTED:-false}" = true ] || exit 1
: "${DC2_STATE_ASSET_ROOT:=/opt/dc2}"
: "${DC2_STATE_CONFIG_DIR:=/etc/dc2-aws}"
"$DC2_STATE_ASSET_ROOT/deploy/aws/state/mount-guard.sh"
"$DC2_STATE_ASSET_ROOT/deploy/aws/state/capacity-check.sh"
for file in "$DC2_STATE_CONFIG_DIR/state.env" "$DC2_STATE_CONFIG_DIR/origin-gate.conf"; do
    [ -f "$file" ] && [ ! -L "$file" ] || exit 1
    [ "$(stat -c %a "$file")" = 600 ] || exit 1
    [ "$(stat -c %u "$file")" = 0 ] || exit 1
done
# Existing owner bootstrap is reused. Only state services are in this file.
exec docker compose --project-name dc2-aws-state --env-file "$DC2_STATE_CONFIG_DIR/state.env" \
    -f "$DC2_STATE_ASSET_ROOT/deploy/aws/state/compose.yml" up -d --no-build
