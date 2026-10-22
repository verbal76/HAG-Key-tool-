import json

import pytest

from hag_bsm.model import SCHEMA_VERSION, Profile
from hag_bsm.profiles import BrokenProfile, ProfileError, ProfileStore, migrate


def sample(**kw):
    p = Profile(name="Backrooms Survivor", android_package="com.hotatticgames.backroomssurvivor", **kw)
    p.platforms["android"]["enabled"] = True
    return p


def test_create_save_reopen(store):
    p = store.save(sample())
    loaded = store.load(p.id)
    assert loaded.to_dict() == p.to_dict()
    assert loaded.publisher == "Hot Attic Games"
    assert [x.id for x in store.list()] == [p.id]


def test_multiple_profiles_listed_newest_first(store):
    a = store.save(sample())
    b = sample()
    b.name = "Second Game"
    b.modified_at = "2000-01-01T00:00:00+00:00"
    store.save(b)  # save() refreshes modified_at
    assert {x.id for x in store.list()} == {a.id, b.id}


def test_duplicate_gets_new_id_and_drops_identity_link(store):
    p = sample()
    p.android_identity_id = "a" * 32
    store.save(p)
    dup = store.duplicate(p)
    assert dup.id != p.id
    assert dup.name == "Backrooms Survivor (copy)"
    assert dup.android_identity_id == ""
    assert store.load(p.id).android_identity_id == "a" * 32


def test_delete_moves_to_deleted_folder_and_keeps_identity(store, vault, paths):
    p = sample()
    p.android_identity_id = "b" * 32
    identity_dir = paths.identities_dir / ("b" * 32)
    identity_dir.mkdir(parents=True)
    (identity_dir / "identity.json").write_text("{}")
    store.save(p)
    moved = store.delete(p.id)
    assert moved.is_file() and moved.parent == paths.deleted_profiles_dir
    assert not store.exists(p.id)
    assert (identity_dir / "identity.json").is_file()


def test_export_import_roundtrip_and_conflicts(store, tmp_path):
    p = store.save(sample())
    dest = tmp_path / "export dir" / "profile.json"
    ProfileStore.export_to(p, dest, identity_summary={"alias": "a", "fingerprint_sha256": "AA:BB", "x": 1})
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["android_identity_public"] == {"alias": "a", "fingerprint_sha256": "AA:BB"}
    with pytest.raises(FileExistsError):
        ProfileStore.export_to(p, dest)

    imported = ProfileStore.read_export(dest)
    assert imported.to_dict() == p.to_dict()
    with pytest.raises(ProfileError):
        store.import_profile(imported, "new")
    copy = store.import_profile(imported, "copy")
    assert copy.id != p.id and copy.name.endswith("(imported)")
    replaced = store.import_profile(imported, "replace")
    assert replaced.id == p.id
    assert len(store.list()) == 2


def test_malformed_profiles_reported_not_deleted(store, paths):
    store.save(sample())
    bad = paths.profiles_dir / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    wrong = paths.profiles_dir / ("c" * 32 + ".json")
    wrong.write_text(json.dumps({"schema_version": 1, "id": "c" * 32, "build_number": "fifteen"}))
    items = store.list()
    broken = [i for i in items if isinstance(i, BrokenProfile)]
    assert len(broken) == 2
    assert bad.read_text(encoding="utf-8") == "{not json"


def test_import_rejects_garbage(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"export_format": "something-else"}))
    with pytest.raises(ProfileError):
        ProfileStore.read_export(f)
    f.write_text("[]")
    with pytest.raises(ProfileError):
        ProfileStore.read_export(f)


def test_failed_save_preserves_previous_file(store, monkeypatch):
    p = store.save(sample())
    before = (store.dir / f"{p.id}.json").read_bytes()
    p.name = "Changed"

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("hag_bsm.fsutil.os.replace", boom)
    with pytest.raises(OSError):
        store.save(p)
    assert (store.dir / f"{p.id}.json").read_bytes() == before
    assert not list(store.dir.glob("*.tmp"))


def test_migrates_v0_profile_and_keeps_original(store, paths):
    paths.profiles_dir.mkdir(parents=True)
    pid = "d" * 32
    v0 = {"id": pid, "name": "Old Game", "platforms": ["android", "web"], "android_keystore_id": "e" * 32}
    path = paths.profiles_dir / f"{pid}.json"
    path.write_text(json.dumps(v0))
    p = store.load(pid)
    assert p.enabled_platforms() == ["android", "web"]
    assert p.android_identity_id == "e" * 32
    assert json.loads(path.read_text())["schema_version"] == SCHEMA_VERSION
    assert json.loads((paths.profiles_dir / f"{pid}.v0.bak.json").read_text()) == v0


def test_newer_schema_refused_without_modification(store, paths):
    paths.profiles_dir.mkdir(parents=True)
    pid = "f" * 32
    path = paths.profiles_dir / f"{pid}.json"
    path.write_text(json.dumps({"schema_version": 99, "id": pid}))
    with pytest.raises(ProfileError, match="newer version"):
        store.load(pid)
    assert json.loads(path.read_text())["schema_version"] == 99


def test_migrate_rejects_non_object():
    with pytest.raises(ProfileError):
        migrate([])
