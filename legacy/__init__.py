"""Retired local stack: peer-HTTP Media/Processing and the Redis/RQ worker.

Nothing here is part of the V1 (AWS) submission. V1 services talk only through SQS with
outbox/inbox delivery, so these modules are kept out of every V1 image's COPY set and
``deploy/v1/check_runtime.py`` fails the image build if any of them becomes importable there.
They remain only so the historical local compose stack and its regression tests still run.
"""
