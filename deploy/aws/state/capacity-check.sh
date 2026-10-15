#!/bin/sh
# Explicit startup/session checkpoint, not a backup or pressure-monitoring daemon.
set -eu
: "${DC2_DATA_MOUNT:=/srv/dc2-data}"
free_kib=$(df -Pk "$DC2_DATA_MOUNT" | awk 'NR==2 {print $4}')
root_free_kib=$(df -Pk / | awk 'NR==2 {print $4}')
case "$free_kib:$root_free_kib" in *[!0-9:]*|:|*:|:*) exit 1 ;; esac
if [ "$free_kib" -lt 1048576 ] || [ "$root_free_kib" -lt 1048576 ]; then
    echo 'State refused: preserve at least1GiB free on root and data' >&2
    exit 1
fi
if [ -d "$DC2_DATA_MOUNT/redis" ]; then
    redis_kib=$(du -sk "$DC2_DATA_MOUNT/redis" | awk '{print $1}')
    case "$redis_kib" in *[!0-9]*|'') exit 1 ;; esac
    if [ "$redis_kib" -gt 262144 ]; then
        echo 'State refused: Redis AOF exceeds256MiB budget; inspect privately' >&2
        exit 1
    fi
fi
