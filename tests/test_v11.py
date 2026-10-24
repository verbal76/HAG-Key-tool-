"""Version 1.1: identifiers, project discovery, workflow secret names, platform credentials, profile import, prompt."""

import json
from pathlib import Path

import pytest

from hag_bsm import discovery, identifiers
from hag_bsm.credentials import CONFIGURED, MISSING, NA, OPTIONAL, REQUIRED, requirements
from hag_bsm.model import PLATFORMS, Profile
from hag_bsm.profile_import import decline, import_candidate, scan
from hag_bsm.profiles import ProfileError
from hag_bsm.prompt import generate_prompt
from hag_bsm.secret_names import custom_names, names_for_profile
from hag_bsm.validation import ERROR, WARNING, has_errors, validate_profile

FP = ":".join(["AB"] * 32)


def prof(name="My Medieval Life", *plats, **kw):
    p = Profile(name=name, **kw)
    for k in plats:
        p.platforms[k]["enabled"] = True
    p.stores = ["private"]
    return p


# --- a Godot project and workflow that mirror an existing game (written to a temp copy, never a live repo) ------

def make_godot(root: Path, package="com.hotatticgames.mymedievallife.dev", code=21, workflow_names=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text('[application]\nconfig/name="My Medieval Life"\nconfig/version="0.21.0"\n')
    (root / "export_presets.cfg").write_text(f'''[preset.0]
name="Android"
platform="Android"
[preset.0.options]
package/unique_name="{package}"
version/code={code}
version/name="0.21.0"
[preset.1]
name="Windows Desktop"
platform="Windows Desktop"
[preset.1.options]
application/product_name="x"
[preset.2]
name="Linux"
platform="Linux/X11"
''')
    names = workflow_names or {"keystore_base64": "ANDROID_KEYSTORE_B64", "keystore_password": "ANDROID_KEYSTORE_PASSWORD",
                                "key_alias": "ANDROID_KEY_ALIAS", "key_password": "ANDROID_KEY_PASSWORD"}
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "release.yml").write_text("jobs:\n  build:\n    env:\n" + "".join(
        f"      V{i}: ${{{{ secrets.{n} }}}}\n" for i, n in enumerate(names.values())) + "      TOKEN: ${{ secrets.GITHUB_TOKEN }}\n")
    return root


# --- identifiers -----------------------------------------------------------------------------------------------

def test_identifier_proposals_are_valid_suggestions():
    ids = identifiers.propose_identifiers("Hot Attic Games", "My Medieval Life")
    assert ids["android"] == ids["apple"] == ids["desktop"] == "com.hotatticgames.mymedievallife"
    assert ids["android_dev"] == "com.hotatticgames.mymedievallife.dev"
    odd = identifiers.propose_identifiers("Hot Attic Games", "7 Days Class")
    p = prof("7 Days Class", "android", "ios", android_package=odd["android"], apple_bundle_id=odd["apple"])
    assert not has_errors(validate_profile(p))   # an Android-invalid name is repaired, an Apple-valid one is kept


def test_dev_identifier_is_separate_from_release_channel_and_validated():
    p = prof("G", "android", android_package="com.a.g", release_channel="private_testing")
    assert p.effective_android_id() == "com.a.g"            # Private Testing alone never adds .dev
    p.v11.use_dev_identifier, p.v11.android_dev_package = True, "com.a.g.dev"
    assert p.effective_android_id() == "com.a.g.dev"
    assert not has_errors(validate_profile(p))
    p.v11.android_dev_package = "com.class.g"
    assert any(i.field == "android_dev_package" and i.level == ERROR for i in validate_profile(p))
    p.v11.android_dev_package = "com.a.g"
    assert any(i.field == "android_dev_package" and i.level == WARNING for i in validate_profile(p))


def test_registry_warns_per_platform_ecosystem_only():
    a = prof("A", "android", "ios", android_package="com.x.a", apple_bundle_id="com.x.a")
    b = prof("B", "android", android_package="com.x.a")            # same Android id as A
    c = prof("C", "windows", desktop_app_id="com.x.a")             # same text, different ecosystem
    warns = [i for i in validate_profile(b, others=[a, c]) if i.level == WARNING and i.field == "android_package"]
    assert len(warns) == 1 and "“A”" in warns[0].message
    assert identifiers.find_conflicts(c, [a, b]) == []
    assert b.android_package == "com.x.a"                           # never silently modified


# --- existing project discovery ---------------------------------------------------------------------------------

def test_godot_discovery_reads_identifiers_and_build(tmp_path):
    d = discovery.inspect_project(make_godot(tmp_path / "game"))
    assert (d.engine, d.android_package, d.version_code, d.version) == ("godot", "com.hotatticgames.mymedievallife.dev", 21, "0.21.0")
    assert d.platforms == ["android", "windows", "linux"]
    assert d.desktop_app_id == "" and any("desktop" in n for n in d.notes)   # unresolved, not invented


def test_placeholder_package_is_unresolved(tmp_path):
    d = discovery.inspect_project(make_godot(tmp_path / "g", package="com.example.$genname"))
    assert d.android_package == "" and any("placeholder" in n for n in d.notes)


def test_unity_gradle_and_unknown_folders(tmp_path):
    u = tmp_path / "u" / "ProjectSettings"
    u.mkdir(parents=True)
    (u / "ProjectSettings.asset").write_text("PlayerSettings:\n  productName: Foo\n  bundleVersion: 1.2\n  AndroidBundleVersionCode: 7\n"
                                              "  applicationIdentifier:\n    Android: com.u.foo\n    iPhone: com.u.foo.ios\n  other: 1\n")
    d = discovery.inspect_project(tmp_path / "u")
    assert (d.engine, d.android_package, d.apple_bundle_id, d.version_code) == ("unity", "com.u.foo", "com.u.foo.ios", 7)
    g = tmp_path / "g" / "app"
    g.mkdir(parents=True)
    (g / "build.gradle").write_text('android { defaultConfig { applicationId "com.g.app"\n versionCode 3\n versionName "2.0" } }')
    assert discovery.inspect_project(tmp_path / "g").android_package == "com.g.app"
    empty = discovery.inspect_project(tmp_path)   # contains the folders above but is itself not a project root
    assert isinstance(empty.engine, str)
    with pytest.raises(discovery.DiscoveryError):
        discovery.inspect_project(tmp_path / "nope")


def test_inspection_never_writes_to_the_project(tmp_path):
    root = make_godot(tmp_path / "game")
    before = {f: f.read_bytes() for f in root.rglob("*") if f.is_file()}
    discovery.inspect_project(root)
    discovery.inspect_workflows(root)
    assert before == {f: f.read_bytes() for f in root.rglob("*") if f.is_file()}


# --- My Medieval Life regression (safe copy) ---------------------------------------------------------------------

def mml_profile(tmp_path):
    root = make_godot(tmp_path / "mml")
    p = prof("My Medieval Life", "android", "windows", "linux", android_package="", build_number=1, version="1.0.0")
    p.android_identity_id = "a" * 32
    d = discovery.inspect_project(root)
    diffs = identifiers.plan_changes(p, d)
    notes = identifiers.apply_choices(p, d, diffs, {})        # defaults: preserve the project's own values
    return root, p, d, diffs, notes


def test_mml_preserves_dev_identifier_build_and_identity(tmp_path):
    root, p, d, diffs, notes = mml_profile(tmp_path)
    assert p.android_package == "com.hotatticgames.mymedievallife.dev"
    assert p.build_number == 21 and p.version == "0.21.0"            # never reset to 1
    assert p.android_identity_id == "a" * 32                          # identity link untouched
    android = next(x for x in diffs if x.field == "android_package")
    assert android.generated == "com.hotatticgames.mymedievallife" and "DEVELOPMENT variant" in android.consequence
    assert android.default_choice == "existing"
    assert not any(i.field == "apple_bundle_id" for i in validate_profile(p))      # no Apple requirements
    assert not any(r.level == REQUIRED and r.platform in ("windows", "linux", "ios", "macos") for r in requirements(p, True))


def test_mml_adopting_the_production_id_warns_and_build_cannot_go_backwards(tmp_path):
    root, p, d, diffs, _ = mml_profile(tmp_path)
    p.android_package = "com.hotatticgames.mymedievallife"
    assert any(i.field == "android_package" and "different application" in i.message for i in validate_profile(p))
    p.build_number = 1
    assert any(i.field == "build_number" and i.level == ERROR for i in validate_profile(p))
    p2 = prof("My Medieval Life", "android", android_package="x.y")
    identifiers.apply_choices(p2, d, diffs, {"build_number": ("custom", "1")})
    assert p2.build_number == 21   # a custom lower value is raised, never lowered below the project


def test_workflow_mismatch_is_reported_with_options_and_never_regenerates_keys(tmp_path):
    root, p, d, *_ = mml_profile(tmp_path)
    info = discovery.inspect_workflows(root)
    assert info.files == ["release.yml"] and "GITHUB_TOKEN" not in info.secrets
    cmp = discovery.compare_names(names_for_profile(p), info)
    assert cmp.inspected and not cmp.aligned and all(r[3] == "mismatch" for r in cmp.rows)
    keys = [o[0] for o in discovery.workflow_options(names_for_profile(p))]
    assert keys == ["adapt_workflow", "use_workflow_names", "custom_mapping"]
    p.v11.workflow_info, p.v11.workflow_choice = info.to_dict(), "adapt_workflow"
    text = generate_prompt(p, {"alias": "a", "fingerprint_sha256": FP, "store_type": "PKCS12"})
    assert "ANDROID_RELEASE_KEYSTORE_BASE64" in text and "workflow reads ANDROID_KEYSTORE_B64" in text
    assert "Update every workflow reference" in text and "never a reason to generate a new keystore" in text
    assert "Continue build numbering from 21" in text and "Keep the package name com.hotatticgames.mymedievallife.dev" in text
    assert "ONE password" in text and "apksigner verify" in text
    assert "Apple" not in text and "provisioning" not in text


def test_use_workflow_names_option_and_aligned_workflow(tmp_path):
    root, p, d, *_ = mml_profile(tmp_path)
    info = discovery.inspect_workflows(root)
    p.v11.secret_mode, p.v11.secret_custom = "workflow", dict(info.signing_secrets)
    p.v11.workflow_info, p.v11.workflow_choice = info.to_dict(), "use_workflow_names"
    names = names_for_profile(p)
    assert names["keystore_base64"] == "ANDROID_KEYSTORE_B64"
    text = generate_prompt(p, {"alias": "a", "fingerprint_sha256": FP})
    assert "ANDROID_KEYSTORE_B64" in text and "already reads the configured names" in text
    assert discovery.compare_names(names, info).aligned


def test_custom_secret_names_validation():
    ok = {"keystore_base64": "MY_KS", "keystore_password": "MY_KSP", "key_alias": "MY_ALIAS", "key_password": "MY_KP"}
    assert custom_names(ok) == ok
    for bad in ({**ok, "key_alias": "bad name"}, {**ok, "key_password": "MY_KS"}, {**ok, "key_alias": ""}, {**ok, "key_alias": "GITHUB_X"}):
        with pytest.raises(ValueError):
            custom_names(bad)
    p = prof("G", "android", android_package="com.a.g")
    p.v11.secret_mode, p.v11.secret_custom = "custom", {**ok, "key_alias": "bad name"}
    assert any(i.field == "secret_custom" and i.level == ERROR for i in validate_profile(p))


# --- platform-aware credentials --------------------------------------------------------------------------------------

def by_key(p, present=False):
    return {r.key: r for r in requirements(p, present)}


def test_credentials_follow_selected_platforms():
    win_linux = by_key(prof("G", "windows", "linux"))
    assert win_linux["android_keystore"].status == NA and win_linux["windows_codesign"].level == OPTIONAL
    assert win_linux["ios_certificate"].status == NA and win_linux["linux_signing"].status == NA
    apple = by_key(prof("G", "ios", "macos"))
    assert apple["ios_certificate"].level == apple["ios_profile"].level == REQUIRED and apple["macos_developer_id"].level == OPTIONAL
    web = by_key(prof("G", "web"))
    assert web["web_deploy"].status == NA
    w = prof("G", "web"); w.v11.web_deployment = True
    assert by_key(w)["web_deploy"].level == REQUIRED and by_key(w)["web_deploy"].status == MISSING
    w.v11.attested = ["web_deploy"]
    assert by_key(w)["web_deploy"].status == CONFIGURED


def test_deselecting_android_keeps_identity_and_flags_it_as_kept():
    p = prof("G", "windows"); p.android_identity_id = "b" * 32
    r = by_key(p, present=True)["android_keystore"]
    assert r.level == "not_applicable" and r.status == CONFIGURED and "kept" in r.detail
    assert p.android_identity_id == "b" * 32


# --- profile discovery and migration-safe import ----------------------------------------------------------------------

def v0(pid="d" * 32):
    return {"id": pid, "name": "Old Game", "platforms": ["android", "web"], "android_keystore_id": "e" * 32}


def test_scan_finds_old_profiles_and_import_is_safe(store, paths):
    paths.config_root.mkdir(parents=True)
    legacy = paths.config_root / "legacy"
    legacy.mkdir()
    src = legacy / "old.json"
    src.write_text(json.dumps(v0()))
    (paths.config_root / "settings.json").write_text("{}")
    (legacy / "unrelated.json").write_text('{"hello": 1}')
    found = scan(paths.config_root, store)
    assert [(c.path.name, c.status, c.fmt) for c in found] == [("old.json", "new", "v0")]
    before = src.read_bytes()
    saved = import_candidate(store, paths.config_root, found[0])
    assert saved.android_identity_id == "e" * 32 and store.exists(saved.id)
    assert src.read_bytes() == before                                     # original preserved
    backups = list((paths.config_root / "migration_backups").iterdir())
    assert len(backups) == 1 and backups[0].read_bytes() == before         # verified backup kept
    assert scan(paths.config_root, store)[0].status == "registered"


def test_declined_files_are_not_offered_again_until_changed_or_forced(store, paths):
    paths.config_root.mkdir(parents=True)
    f = paths.config_root / "old.json"
    f.write_text(json.dumps(v0()))
    first = scan(paths.config_root, store)
    decline(paths.config_root, first)
    assert scan(paths.config_root, store)[0].status == "declined"
    assert scan(paths.config_root, store, force=True)[0].status == "new"
    f.write_text(json.dumps({**v0(), "name": "Changed"}))
    assert scan(paths.config_root, store)[0].status == "new"


def test_conflicts_are_resolved_by_the_owner_and_failed_import_rolls_back(store, paths, monkeypatch):
    existing = store.save(prof("Keep Me", "android", android_package="com.a.b"))
    paths.config_root.mkdir(parents=True, exist_ok=True)
    f = paths.config_root / "other.json"
    f.write_text(json.dumps({**existing.to_dict(), "name": "Different"}))
    cand = scan(paths.config_root, store)[0]
    assert cand.status == "conflict"
    with pytest.raises(ProfileError):
        import_candidate(store, paths.config_root, cand, "new")            # never overwrites silently
    assert store.load(existing.id).name == "Keep Me"
    copy = import_candidate(store, paths.config_root, cand, "copy")
    assert copy.id != existing.id and store.load(existing.id).name == "Keep Me"

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store, "import_profile", boom)
    with pytest.raises(ProfileError, match="rolled back"):
        import_candidate(store, paths.config_root, cand, "replace")
    assert store.load(existing.id).name == "Keep Me"                        # previous state restored


def test_invalid_candidates_are_reported_not_imported(store, paths):
    paths.config_root.mkdir(parents=True)
    (paths.config_root / "bad.json").write_text(json.dumps({"id": "zz", "name": "Bad", "schema_version": 1}))
    c = scan(paths.config_root, store)[0]
    assert c.status == "invalid" and not c.importable


# --- compatibility ---------------------------------------------------------------------------------------------------------

def test_profiles_without_v11_data_stay_schema_1_and_identical():
    p = prof("G", "android", android_package="com.a.g")
    d = p.to_dict()
    assert d["schema_version"] == 1 and "v11" not in d
    p.v11.project_kind = "new"
    d2 = p.to_dict()
    assert d2["schema_version"] == 2 and d2["v11"] == {"project_kind": "new"}
    back = Profile.from_dict(json.loads(json.dumps(d2)))
    assert back.v11.project_kind == "new" and back.to_dict() == d2
    assert Profile.from_dict(d).to_dict() == d
    d2["v11"]["unknown_future_field"] = 1                      # written by a newer build: ignored
    assert Profile.from_dict(d2).v11.project_kind == "new"
    d2["v11"]["use_dev_identifier"] = "yes"
    with pytest.raises(ValueError):
        Profile.from_dict(d2)


def test_default_prompt_has_no_v11_section_and_never_leaks_secrets():
    p = prof("G", "android", android_package="com.a.g")
    assert "PROJECT STATUS" not in generate_prompt(p, {"alias": "secretalias", "fingerprint_sha256": FP})
    p.v11.project_kind = "existing"
    text = generate_prompt(p, {"alias": "secretalias", "fingerprint_sha256": FP, "store_type": "PKCS12"})
    assert "secretalias" not in text and "PROJECT STATUS AND PRESERVATION" in text
    assert all(len(t) < 400 for t in text.splitlines() if "password" in t.lower() and "=" in t)
