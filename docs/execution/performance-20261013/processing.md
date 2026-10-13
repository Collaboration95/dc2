# Processing performance evidence — 13 October 2026

Issue [#35](https://github.com/Collaboration95/dc2/issues/35), parent
[#33](https://github.com/Collaboration95/dc2/issues/33).
Base: `87389d178a822f92882e04bf4a0109613b844ffb`.
Tested code/tests head: `bc642f98c9ef4619b6385a5a264f9425e34d2b17` on
`perf/processing-20261013`; this separate report commit changes no executable files.
Production code is identical to the initially shared `841940a`; the subsequent
delta adds two multipart failure/retry tests only. Parent handles secret-gist
publication, independent Sol review, PR and CI. Those gates are not claimed here.

## Finding and decision

`processing/worker/storage.py` previously hashed each completed output through
`hashlib.file_digest`, then called `Minio.fput_object`, which opened and read the
file again. Each primary, HLS segment and playlist incurred two full reads, two
opens and two executor submissions. Installed MinIO 7.2.20 source confirms that
`fput_object` delegates to `put_object`; `put_object` reads bounded parts and sends
buffered bytes to `_upload_part`. Inspect with:

```sh
../../.venv/bin/python - <<'PY'
import inspect
from importlib.metadata import version
from minio import Minio
print(version('minio'))
for method in (Minio.fput_object, Minio.put_object, Minio._upload_part, Minio._execute):
    print(inspect.getsource(method))
PY
```

The change hashes the exact SDK input during its existing read pass. One executor
submission owns file opening, descriptor-based sizing, upload and result checks.
SHA-256 remains complete; metadata is returned only after an acknowledgement,
exact consumed length and EOF check. Empty, short, growing or unacknowledged output
does not return publishable metadata. Multipart buffering, serial part uploads,
transport retry settings, PUT-only permissions, output keys and lease/publication
fences retain their existing behavior. Cancellation can still leave a late PUT;
retained cleanup intents and fenced SQL publication retain responsibility for it.
No encoder, quality, recovery, queue or source-download changes were made.

## Measured result and limits

Local deterministic instrumentation used the actual installed SDK reader and
multipart loop, replacing network operations. All payload digests matched.

| Output bytes | Base bytes read | Head bytes read | Base/head opens | Base/head executor submissions |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 128 | 64 | 2 / 1 | 2 / 1 |
| 262144 | 524288 | 262144 | 2 / 1 | 2 / 1 |
| 5242897 | 10485794 | 5242897 | 2 / 1 | 2 / 1 |

**Measured:** 50% fewer application file bytes read, one fewer open and one fewer
executor submission per acknowledged output. The multipart case retains the SDK's
5 MiB + 17-byte part split. This counts logical reads, not physical disk traffic.
**Inferred:** lower worker I/O and scheduling overhead, especially for many HLS
objects. End-to-end speed, CPU, peak allocation, network latency and cloud cost
were not measured. Encoding still dominates representative jobs. No live VM,
Docker, FFmpeg, cloud or concurrent heavy benchmark was used.

Reproduce the exact before/after comparison from this worktree:

```sh
../../.venv/bin/python - <<'PY'
import asyncio, hashlib, json, runpy, subprocess, tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
import pytest
from minio import Minio
from processing.worker.storage import OutputStore
helpers = runpy.run_path('tests/processing/test_storage_performance.py')
baseline = ModuleType('baseline_storage')
exec(subprocess.check_output(['git', 'show', '87389d178a822f92882e04bf4a0109613b844ffb:processing/worker/storage.py'], text=True), baseline.__dict__)
async def compare(label, cls, path, size):
    uploaded = hashlib.sha256()
    client = Minio('unused.test', region='us-east-1')
    def record(_bucket, _key, data, *_args):
        uploaded.update(data)
        return SimpleNamespace(etag='ack')
    client._put_object = record
    client._create_multipart_upload = lambda *args: 'upload-id'
    client._upload_part = lambda *args: record(*args).etag
    client._complete_multipart_upload = lambda *args: SimpleNamespace(bucket_name='outputs', object_name='key', version_id=None, etag='ack', http_headers={}, location=None)
    store = cls.__new__(cls)
    store.bucket, store.client = 'outputs', client
    with pytest.MonkeyPatch.context() as monkeypatch:
        counts = helpers['count_file_io'](monkeypatch, path)
        output = await store.put('key', path, 'video/mp4', 'primary')
    assert output['sha256'] == uploaded.hexdigest() == hashlib.sha256(b'x' * size).hexdigest()
    print(json.dumps(dict(source=label, size_bytes=size, **counts, digest_matches=True)))
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'output'
    for size in (64, 262144, 5 * 1024 * 1024 + 17):
        path.write_bytes(b'x' * size)
        asyncio.run(compare('87389d1', baseline.OutputStore, path, size))
        asyncio.run(compare('candidate', OutputStore, path, size))
PY
```

Exit 0; six JSON rows match the table, each with `digest_matches=true`.

## Verification and alternatives

Exact baseline command: `../../.venv/bin/python -m pytest -q -p
scripts.dev.pytest_plugin --offline-fast tests/processing tests/media_engine`:
**247 passed in 1.21s**. Exact final command:

```sh
../../.venv/bin/python -m pytest -q -p scripts.dev.pytest_plugin --offline-fast --cov=processing.worker.storage --cov-report=term-missing tests/processing tests/media_engine
../../.venv/bin/ruff check processing media_engine tests/processing tests/media_engine
git diff --check
```

**260 passed in 1.65s**, changed storage module **100% statement/branch coverage**
(32 statements, four branches); lint and whitespace exit 0. Network is forbidden
by the offline plugin. New tests cover real SDK single/multipart read semantics,
exact part sizes and uploaded digest, incomplete consumption, short/growing/empty
files, missing acknowledgement, upload errors and cancellation/file closure.
Multipart part or completion failure raises before metadata is returned, invokes
SDK abort, and a fresh PUT computes its own accurate size/digest. These are
controlled failure/retry tests, not a real S3 network-retry experiment; no retry
policy is added or changed. Existing supervisor, lifecycle and recovery tests pass.

Rejected alternatives: changing normal MP4 to stream-copy or merging MP4/HLS
encoding risks quality/contract changes; concurrent HLS uploads add in-flight
work and require cancellation/cleanup measurements; queue-registry optimization
and download chunk tuning lacked a measured material cost in this bounded lane.
Retaining separate hashing but combining executor submissions saves scheduling
only and leaves the demonstrated extra full read. No additional dependency or
infrastructure is required by the selected change.
