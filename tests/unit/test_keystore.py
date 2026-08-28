import keyring
import keyring.backend
import keyring.backends.fail
import pytest

from aptiordesk.ai import keystore
from aptiordesk.core.errors import KeystoreUnavailable
from aptiordesk.core.identity import KEYRING_SERVICE, LEGACY_KEYRING_SERVICE


class InMemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture
def memory_backend():
    original = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(original)


@pytest.fixture
def no_backend():
    original = keyring.get_keyring()
    keyring.set_keyring(keyring.backends.fail.Keyring())
    yield
    keyring.set_keyring(original)


def test_set_get_delete_roundtrip(memory_backend):
    keystore.set_key(7, "s3cret")
    assert keystore.get_key(7) == "s3cret"
    keystore.delete_key(7)
    assert keystore.get_key(7) is None


def test_keys_are_namespaced_by_provider(memory_backend):
    keystore.set_key(1, "one")
    keystore.set_key(2, "two")
    assert keystore.get_key(1) == "one"
    assert keystore.get_key(2) == "two"


def test_no_backend_refuses_to_store(no_backend):
    assert not keystore.available()
    with pytest.raises(KeystoreUnavailable):
        keystore.set_key(1, "key")
    assert keystore.get_key(1) is None  # does not raise
    keystore.delete_key(1)  # no-op, does not raise


def test_legacy_key_is_copied_and_verified_without_deleting_source(memory_backend):
    memory_backend.set_password(LEGACY_KEYRING_SERVICE, "provider-9", "legacy-key")

    assert keystore.get_key(9) == "legacy-key"
    assert memory_backend.get_password(KEYRING_SERVICE, "provider-9") == "legacy-key"
    assert memory_backend.get_password(LEGACY_KEYRING_SERVICE, "provider-9") == "legacy-key"
