"""Minimal in-memory fake Firestore, used only in tests.

Real integration testing needs the local emulator (see
scripts/dev_firestore_emulator.sh), which needs a Java 21+ JRE - not
available in every dev environment. This fake lets the auth/ownership
logic be tested everywhere without that. Swap to emulator-backed tests if
the code ever needs a Firestore query feature this fake doesn't implement
(it supports get/set/update/delete/stream/add, where() with "==" filters
only, and update() with a last_update_time precondition). Like real
Firestore, it refuses a list directly inside a list.
"""

import itertools

from google.api_core.exceptions import FailedPrecondition, InvalidArgument

# Stands in for Firestore's per-document update timestamps: every write
# takes the next number, which is all a last_update_time check needs.
_clock = itertools.count(1)


def _refuse_nested_lists(value, inside_list=False):
    """Real Firestore rejects a list whose element is itself a list (maps
    in between are fine). Checked here so tests fail the way production
    would, rather than passing on data Firestore can't store."""
    if isinstance(value, list):
        if inside_list:
            raise InvalidArgument("Property array contains an invalid nested entity.")
        for element in value:
            _refuse_nested_lists(element, inside_list=True)
    elif isinstance(value, dict):
        for element in value.values():
            _refuse_nested_lists(element)


class FakeWriteOption:
    def __init__(self, last_update_time):
        self.last_update_time = last_update_time


class FakeSnapshot:
    def __init__(self, doc_id, data, update_time=None):
        self.id = doc_id
        self._data = data
        self.update_time = update_time

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

    def _times(self):
        return self._store.setdefault(("update_times", self._collection_name), {})

    def set(self, data):
        _refuse_nested_lists(data)
        self._store[self._collection_name][self.id] = dict(data)
        self._times()[self.id] = next(_clock)

    def update(self, data, option=None):
        if option is not None and option.last_update_time != self._times().get(self.id):
            raise FailedPrecondition("document changed since it was read")
        _refuse_nested_lists(data)
        self._store[self._collection_name][self.id].update(data)
        self._times()[self.id] = next(_clock)

    def get(self):
        data = self._store[self._collection_name].get(self.id)
        return FakeSnapshot(self.id, data, self._times().get(self.id))

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
        _refuse_nested_lists(data)
        doc_id = f"auto-{next(self._id_counter)}"
        self._store[self._name][doc_id] = dict(data)
        return (None, FakeSnapshot(doc_id, data))

    def stream(self):
        return [FakeSnapshot(doc_id, data) for doc_id, data in self._store[self._name].items()]

    def where(self, *, filter):
        return FakeQuery(self, [filter])


class FakeQuery:
    """Supports chained .where(filter=FieldFilter(field, "==", value))."""

    def __init__(self, collection, filters):
        self._collection = collection
        self._filters = filters

    def where(self, *, filter):
        return FakeQuery(self._collection, self._filters + [filter])

    def stream(self):
        for f in self._filters:
            assert f.op_string == "==", "the fake only supports == filters"
        return [
            snap
            for snap in self._collection.stream()
            if all(snap.get(f.field_path) == f.value for f in self._filters)
        ]


class FakeFirestore:
    """A Firestore client stand-in backed by a plain dict - one per test."""

    def __init__(self):
        self._store: dict[str, dict] = {}
        self._id_counter = itertools.count(1)

    def collection(self, name):
        return FakeCollection(self._store, name, self._id_counter)

    def write_option(self, last_update_time):
        return FakeWriteOption(last_update_time)
