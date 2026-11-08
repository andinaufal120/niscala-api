"""A file store kept in memory, for tests that must not touch disk or network."""


class MemoryFileStore:
    """A dict-backed `FileStore` that records every call and can be told to fail.

    `objects` maps a key to `(content, content_type)`. `calls` holds
    `(operation, key)` for every call, failed ones included. `fail_on_put` and
    `fail_on_delete` make those operations raise `RuntimeError`.
    """

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_on_put = False
        self.fail_on_delete = False

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.calls.append(("put", key))
        if self.fail_on_put:
            raise RuntimeError("storage unavailable")
        self.objects[key] = (content, content_type)

    def get(self, key: str) -> bytes:
        self.calls.append(("get", key))
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key][0]

    def delete(self, key: str) -> None:
        self.calls.append(("delete", key))
        if self.fail_on_delete:
            raise RuntimeError("storage unavailable")
        self.objects.pop(key, None)

    @property
    def keys(self) -> set[str]:
        return set(self.objects)

    def deleted(self) -> list[str]:
        """The keys `delete` was called with, in order."""
        return [key for operation, key in self.calls if operation == "delete"]
