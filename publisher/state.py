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
        self.data[identity] = key
        self.save()
        return key

    def complete(self, identity):
        self.data.pop(identity, None)
        self.save()

    def save(self):
        private_write(self.path, lambda name: Path(name).write_text(json.dumps(self.data)))


def file_identity(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return [path.name, path.stat().st_size, digest.hexdigest()]
