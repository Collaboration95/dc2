#!/bin/sh
# Existing formatted volume only. No mkfs, automatic device guessing or root fallback.
set -eu
umask 077
: "${DC2_DATA_UUID:?Explicit reviewed filesystem UUID required}"
: "${DC2_DATA_MOUNT:=/srv/dc2-data}"
case "$DC2_DATA_UUID" in *[!A-Za-z0-9-]*|'') exit 1 ;; esac
case "$DC2_DATA_MOUNT" in /*) ;; *) exit 1 ;; esac
if ! mountpoint -q "$DC2_DATA_MOUNT"; then
    echo 'State refused: required data mount missing' >&2
    exit 1
fi
actual=$(findmnt -rn -M "$DC2_DATA_MOUNT" -o UUID)
root_uuid=$(findmnt -rn -M / -o UUID)
options=$(findmnt -rn -M "$DC2_DATA_MOUNT" -o OPTIONS)
if [ "$actual" != "$DC2_DATA_UUID" ] || [ "$actual" = "$root_uuid" ]; then
    echo 'State refused: wrong or root-backed filesystem' >&2
    exit 1
fi
case ",$options," in *,rw,*) ;; *) echo 'State refused: filesystem not writable' >&2; exit 1 ;; esac
