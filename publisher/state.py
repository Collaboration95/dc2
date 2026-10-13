"""Private durable pending intent keys, scoped by public origin and owner."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from publisher.client import private_write


class Intents:
    def __init__(self, path, scope):
        self.path = Path(path)
        self.scope = scope
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def identity(self, operation, value):
        return hashlib.sha256(json.dumps([self.scope, operation, value]).encode()).hexdigest()

    def reserve(self, identity, explicit=None):
        key = explicit or self.data.get(identity) or str(uuid4())
        self.change(identity, key)
        return key

    def complete(self, identity):
        self.change(identity, None)

    def change(self, identity, key):
        previous = self.data.copy()
        if key is None:
            self.data.pop(identity, None)
        else:
            self.data[identity] = key
        try:
            self.save()
        except OSError:
            # Later batch writes must retain everything still persisted on disk.
            self.data = previous
            raise

    def save(self):
        private_write(self.path, lambda name: Path(name).write_text(json.dumps(self.data)))


def file_identity(path):
    with path.open("rb") as stream:
        # Reuse the standard library's bounded buffer while hashing every byte.
        digest = hashlib.file_digest(stream, "sha256")
    return [path.name, path.stat().st_size, digest.hexdigest()]
