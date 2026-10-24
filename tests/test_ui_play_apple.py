"""UI behaviour for the Google Play and Apple groups (offscreen Qt, temporary credentials only)."""

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding  # noqa: E402

from hag_bsm import apple  # noqa: E402
from hag_bsm.ui import dialogs  # noqa: E402
from test_play_apple import make_cert, make_profile_file  # noqa: E402
from test_ui import open_new, qapp, wait_until, window  # noqa: E402,F401

SIGNING, SECRETS, PROMPT = 3, 4, 5


def test_group_visibility_is_driven_by_platform_and_store(window, qapp):
    open_new(window)
    window.nav.setCurrentRow(SIGNING)
    page, ctx = window.pages[SIGNING], window.ctx
    assert not page.play.isVisibleTo(page) and not page.apple.isVisibleTo(page)
    ctx.profile.stores = ["google_play"]
    ctx.mark_dirty()
    assert page.play.isVisibleTo(page) and not page.apple.isVisibleTo(page)
    ctx.profile.platforms["ios"]["enabled"] = True
    ctx.mark_dirty()
    assert page.apple.isVisibleTo(page)
    ids = window.pages[2]
    assert ids.apple_dev_id.isVisibleTo(ids) and ids.id_rows["apple_bundle_id"][1].isVisibleTo(ids)
    ctx.profile.platforms["ios"]["enabled"] = False
    ctx.mark_dirty()
    assert not page.apple.isVisibleTo(page) and not ids.apple_dev_id.isVisibleTo(ids)
    assert window.nav.item(SIGNING).text() == "Signing Identities"


def test_new_android_project_upload_key_flow(window, qapp, monkeypatch, keytool_tools, tmp_path):
    open_new(window)
    ctx, page = window.ctx, window.pages[SIGNING]
    ctx.profile.stores = ["google_play"]
    ctx.mark_dirty()
    direct = ctx.vault.generate(keytool_tools, "UI Game", "direct", "d.jks", "CN=Direct")
    ctx.link_identity(direct.id)
    before = direct.fingerprint_sha256

    monkeypatch.setattr(dialogs.GenerateIdentityDialog, "exec", lambda self: dialogs.GenerateIdentityDialog.Accepted)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    page.play.generate()
    wait_until(qapp, lambda: not ctx.busy)
    up = ctx.upload_identity()
    assert up is not None and up.id != direct.id and up.label.endswith("upload key")
    assert ctx.profile.android_identity_id == direct.id and ctx.identity().fingerprint_sha256 == before   # direct key untouched
    assert "SEPARATE" in page.play.relation.text() and page.play.v_sha256.value() == up.fingerprint_sha256
    assert page.play.v_sha1.value() == up.fingerprint_sha1
    text = page.play.checks.text()
    assert "Upload signing key" in text and "App-signing" in text or "app-signing" in text

    # PEM export for Play Console: public certificate only, never overwrites
    out = tmp_path / "up.pem"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    page.play.export_pem()
    wait_until(qapp, lambda: not ctx.busy)
    assert out.read_text().startswith("-----BEGIN CERTIFICATE-----") and "PRIVATE" not in out.read_text()
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    page.play.export_pem()
    assert shown and "never overwritten" in shown[0]

    # pasted fingerprints: bad input is rejected and not stored; good input is normalised
    f = page.play.f_sha256
    f.edit.setText("12:34")
    assert f.msg.text() and ctx.profile.v11.play_signing_sha256 == ""
    f.edit.setText("sha256: " + "ab" * 32)
    assert ctx.profile.v11.play_signing_sha256 == ":".join(["AB"] * 32) and not f.msg.text()
    page.play.f_console.edit.setText(up.fingerprint_sha256)
    assert "matches the local upload key" in page.play.checks.text()

    # prompt: three roles, unverified Google key, names only
    prompt = window.pages[PROMPT].text.toPlainText()
    assert "GOOGLE PLAY SIGNING" in prompt and "NOT verified by the manager" in prompt and "PLAY_UPLOAD_KEY_ALIAS" in prompt
    creds = ctx.vault.credentials(up.id)
    assert creds.store_password not in prompt and "BEGIN" not in prompt

    # secrets page lists separate upload names with masked values
    window.nav.setCurrentRow(SECRETS)
    card = window.pages[SECRETS].platform_card
    assert card.isVisibleTo(window.pages[SECRETS])
    shown_text = " ".join(w.text() for w in card.findChildren(type(page.play.relation)))
    assert creds.store_password not in shown_text


def test_use_direct_key_as_upload_and_existing_upload_not_replaced(window, qapp, monkeypatch, keytool_tools):
    open_new(window)
    ctx, page = window.ctx, window.pages[SIGNING]
    ctx.profile.stores = ["google_play"]
    ctx.mark_dirty()
    direct = ctx.vault.generate(keytool_tools, "UI Game", "direct", "d.jks", "CN=Direct")
    ctx.link_identity(direct.id)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    page.play.use_direct()
    assert ctx.profile.v11.play_upload_identity_id == direct.id and "SAME" in page.play.relation.text()
    names = window.pages[PROMPT].text.toPlainText()
    assert "the existing Android secrets" in names

    # generating while an upload key exists demands REPLACE (dialog confirm field) and never deletes anything
    ids_before = {r.id for r in ctx.vault.list()}
    dlg = dialogs.GenerateIdentityDialog(ctx.profile, ctx.upload_identity())
    assert dlg.confirm is not None and "REPLACE" in dlg.validate()
    assert {r.id for r in ctx.vault.list()} == ids_before


def test_existing_android_project_keeps_build_number_and_identity(window, qapp):
    p = open_new(window)
    ctx = window.ctx
    p.stores = ["google_play"]
    p.v11.project_kind = "existing"
    p.v11.discovered = {"version_code": 57, "android_package": "com.hotatticgames.uigame"}
    p.build_number = 57
    ctx.mark_dirty()
    prompt = window.pages[PROMPT].text.toPlainText()
    assert "EXISTING project" in prompt and "Continue build numbering from 57" in prompt
    assert "Never reset the build number" in prompt
    p.build_number = 1                                       # the manager default must not silently win
    ctx.mark_dirty()
    assert window.pages[PROMPT].text.toPlainText() == "" or "build 57" in window.pages[PROMPT].issues_badge.text()


def test_apple_configuration_walkthrough(window, qapp, monkeypatch, tmp_path):
    p = open_new(window, platforms=("ios",))
    p.apple_bundle_id = "com.hotatticgames.uigame"
    window.ctx.mark_dirty()
    page = window.pages[SIGNING]
    key, cert = make_cert("Apple Distribution: Test Org (ABCDE12345)", "ABCDE12345")
    cer = tmp_path / "dist.cer"
    cer.write_bytes(cert.public_bytes(Encoding.DER))
    prof = tmp_path / "app.mobileprovision"
    prof.write_bytes(make_profile_file(cert, bundle="com.hotatticgames.uigame"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(cer), ""))
    page.apple.add_certificate()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(prof), ""))
    page.apple.add_profile()
    v = window.ctx.profile.v11
    assert v.apple_team_id == "ABCDE12345" and len(v.apple_certs) == 1 and len(v.apple_profiles) == 1
    assert v.apple_certs[0]["kind"] == "distribution" and not v.apple_certs[0]["private_key_present"]
    assert "macOS" in page.apple.checks.text() and "✖" not in page.apple.checks.text()
    prompt = window.pages[PROMPT].text.toPlainText()
    assert "APPLE SIGNING AND PROVISIONING" in prompt and "ABCDE12345" in prompt and "Do not publish, notarize" in prompt
    # requirements now count the imported metadata as recorded (not verified)
    req = window.pages[SIGNING].req_card
    assert any("Apple distribution certificate" in w.text() for w in req.findChildren(type(page.apple.checks)))
    # a mismatching bundle identifier is flagged
    p.apple_bundle_id = "com.someone.else"
    window.ctx.mark_dirty()
    assert "not this project" in page.apple.checks.text()
    # Team ID typed wrongly is rejected, not stored
    page.apple.team.edit.setText("bad")
    assert page.apple.team.msg.text() and v.apple_team_id == "ABCDE12345"
    # secrets page suggests names only
    card = window.pages[SECRETS].platform_card
    window.nav.setCurrentRow(SECRETS)
    assert card.isVisibleTo(window.pages[SECRETS])
