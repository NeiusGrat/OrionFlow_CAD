"""§8.1 held_out mechanics: encrypted at rest (held_out_crypto.py, a
`cryptography`/Fernet substitute for `age` -- see that module's
docstring for why), decrypted only with ORION_RELEASE_GATE=1 and the
configured key. Tests build their own throwaway key/ciphertext in a tmp
dir rather than relying on the one demo file committed to the repo, which
exists to show the mechanism works end to end against real ciphertext --
test_committed_demo_task_decrypts_with_its_documented_key below is the
one test that touches it.
"""

import os

import pytest
import yaml

from orion_harness.tasks.held_out_crypto import (
    HELD_OUT_KEY_ENV,
    HeldOutKeyMissing,
    decrypt,
    encrypt,
    generate_key,
)
from orion_harness.tasks.loader import RELEASE_GATE_ENV, SplitAccessDenied, load_split

from conftest import TASKS_ROOT

TASK_YAML = """\
task_id: sealed_example
family: prismatic_plate
pillar: reconstruct
split: held_out
difficulty: 1
provenance: hand_authored
prompt: "sealed"
checks:
  - {name: schema_valid, verifier: tier0.schema, kind: gate}
timeout_s: 60
"""


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv(RELEASE_GATE_ENV, raising=False)
    monkeypatch.delenv(HELD_OUT_KEY_ENV, raising=False)


def test_encrypt_decrypt_roundtrip(clean_env, monkeypatch):
    key = generate_key()
    monkeypatch.setenv(HELD_OUT_KEY_ENV, key)
    ciphertext = encrypt(TASK_YAML.encode("utf-8"))
    assert ciphertext != TASK_YAML.encode("utf-8")
    assert decrypt(ciphertext) == TASK_YAML.encode("utf-8")


def test_encrypt_without_key_raises(clean_env):
    with pytest.raises(HeldOutKeyMissing):
        encrypt(TASK_YAML.encode("utf-8"))


def test_decrypt_with_wrong_key_fails(clean_env, monkeypatch):
    monkeypatch.setenv(HELD_OUT_KEY_ENV, generate_key())
    ciphertext = encrypt(TASK_YAML.encode("utf-8"))

    monkeypatch.setenv(HELD_OUT_KEY_ENV, generate_key())  # a different key
    with pytest.raises(ValueError):
        decrypt(ciphertext)


def test_load_split_held_out_without_release_gate_is_denied(clean_env, tmp_path):
    (tmp_path / "held_out").mkdir()
    with pytest.raises(SplitAccessDenied):
        load_split(tmp_path, "held_out")


def test_load_split_held_out_end_to_end(clean_env, monkeypatch, tmp_path):
    key = generate_key()
    monkeypatch.setenv(HELD_OUT_KEY_ENV, key)
    ciphertext = encrypt(TASK_YAML.encode("utf-8"))

    held_out_dir = tmp_path / "held_out"
    held_out_dir.mkdir()
    (held_out_dir / "sealed_example.yaml.enc").write_bytes(ciphertext)

    monkeypatch.setenv(RELEASE_GATE_ENV, "1")
    tasks = load_split(tmp_path, "held_out")
    assert len(tasks) == 1
    assert tasks[0].task_id == "sealed_example"


def test_load_split_held_out_rejects_content_with_wrong_declared_split(
    clean_env, monkeypatch, tmp_path
):
    key = generate_key()
    monkeypatch.setenv(HELD_OUT_KEY_ENV, key)
    wrong_split_yaml = TASK_YAML.replace("split: held_out", "split: dev")
    ciphertext = encrypt(wrong_split_yaml.encode("utf-8"))

    held_out_dir = tmp_path / "held_out"
    held_out_dir.mkdir()
    (held_out_dir / "sealed_example.yaml.enc").write_bytes(ciphertext)

    monkeypatch.setenv(RELEASE_GATE_ENV, "1")
    with pytest.raises(SplitAccessDenied):
        load_split(tmp_path, "held_out")


def test_committed_demo_task_decrypts_with_its_documented_key(clean_env, monkeypatch):
    """The one real, checked-in ciphertext. Its key is disclosed in the
    session report (it is a demo, not a real secret) -- this test is the
    regression check that the committed .enc file and this key still
    agree."""

    monkeypatch.setenv(HELD_OUT_KEY_ENV, "sLlu8ew8QET83lVODV-z5RJC_KQsCmtaeSjK2S62YVM=")
    monkeypatch.setenv(RELEASE_GATE_ENV, "1")
    tasks = load_split(TASKS_ROOT, "held_out")
    assert any(t.task_id == "held_out_demo_washer" for t in tasks)
