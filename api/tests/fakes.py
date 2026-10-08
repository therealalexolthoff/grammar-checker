"""Minimal in-memory fake Firestore, used only in tests.

Real integration testing needs the local emulator (see
scripts/dev_firestore_emulator.sh), which needs a Java 21+ JRE - not
available in every dev environment. This fake lets the auth/ownership
logic be tested everywhere without that. Swap to emulator-backed tests if
the code ever needs a Firestore query feature this fake doesn't implement
(it only supports get/set/update/delete/stream/add - enough for Phase 2).
"""

import itertools


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def get(self, field):
        return self._data.get(field)

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocRef:
    def __init__(self, store, collection_name, doc_id):
        self._store = store
        self._collection_name = collection_name
        self.id = doc_id

    def set(self, data):
        self._store[self._collection_name][self.id] = dict(data)

    def update(self, data):
        self._store[self._collection_name][self.id].update(data)

    def get(self):
        data = self._store[self._collection_name].get(self.id)
        return FakeSnapshot(self.id, data)

    def delete(self):
        self._store[self._collection_name].pop(self.id, None)


class FakeCollection:
    def __init__(self, store, name, id_counter):
        self._store = store
        self._name = name
        self._id_counter = id_counter
        self._store.setdefault(name, {})

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = f"auto-{next(self._id_counter)}"
        return FakeDocRef(self._store, self._name, doc_id)

    def add(self, data):
        doc_id = f"auto-{next(self._id_counter)}"
        self._store[self._name][doc_id] = dict(data)
        return (None, FakeSnapshot(doc_id, data))

    def stream(self):
        return [FakeSnapshot(doc_id, data) for doc_id, data in self._store[self._name].items()]


class FakeFirestore:
    """A Firestore client stand-in backed by a plain dict - one per test."""

    def __init__(self):
        self._store: dict[str, dict] = {}
        self._id_counter = itertools.count(1)

    def collection(self, name):
        return FakeCollection(self._store, name, self._id_counter)
