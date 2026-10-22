"""UI tests running the real widgets on Qt's offscreen platform."""

import time

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from hag_bsm.model import Profile  # noqa: E402
from hag_bsm.ui import dialogs  # noqa: E402
from hag_bsm.ui.app import create_app, dispose  # noqa: E402
from hag_bsm.ui.context import AppContext  # noqa: E402
from hag_bsm.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = create_app(["test"])
    yield app
    dispose(app)  # what the real application does after its event loop ends


@pytest.fixture
def window(qapp, paths):
    ctx = AppContext(paths)
    win = MainWindow(ctx)
    win.show()
    yield win
    ctx.dirty = False
    win.close()


def wait_until(qapp, cond, timeout=120):
    end = time.time() + timeout
    while not cond():
        qapp.processEvents()
        if time.time() > end:
            raise TimeoutError
        time.sleep(0.01)


def open_new(win, name="UI Game", platforms=("android",)):
    p = Profile(name=name, android_package="com.hotatticgames.uigame")
    for k in platforms:
        p.platforms[k]["enabled"] = True
    p.stores = ["private"]
    win.ctx.store.save(p)
    win.ctx.open_profile(p)
    return p


def test_navigation_requires_project(window, qapp):
    window.nav.setCurrentRow(3)
    qapp.processEvents()
    assert window.stack.currentIndex() == 0          # bounced back to Projects
    window.nav.setCurrentRow(6)
    assert window.stack.currentIndex() == 6          # Settings works without a project
    open_new(window)
    for row in range(window.nav.count()):
        window.nav.setCurrentRow(row)
        qapp.processEvents()
        assert window.stack.currentIndex() == row


def test_edit_save_and_reopen_after_restart(window, qapp, paths):
    p = open_new(window)
    details = window.pages[1]
    window.nav.setCurrentRow(1)
    details.name.setText("Renamed Game")
    details.version.setText("2.1.0")
    details.build.setValue(42)
    assert window.ctx.dirty and window.dirty_label.isVisible()
    window.ctx.save_profile()
    assert not window.ctx.dirty
    window.close()

    ctx2 = AppContext(paths)
    win2 = MainWindow(ctx2)
    win2.open_last_profile()
    assert ctx2.profile.id == p.id
    assert (ctx2.profile.name, ctx2.profile.version, ctx2.profile.build_number) == ("Renamed Game", "2.1.0", 42)
    assert win2.pages[1].name.text() == "Renamed Game"
    win2.close()


def test_unsaved_changes_prompt(window, qapp, monkeypatch):
    open_new(window)
    window.pages[1].name.setText("Changed")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    assert not window.projects_page.confirm_discard()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    assert window.projects_page.confirm_discard()


def test_platform_and_store_checkboxes_update_profile(window, qapp):
    open_new(window, platforms=())
    page = window.pages[2]
    page.platform_boxes["web"].setChecked(True)
    page.format_boxes["web"]["html5"].setChecked(True)
    page.store_boxes["steam"].setChecked(True)
    p = window.ctx.profile
    assert p.is_enabled("web") and p.formats("web") == ["html5"] and "steam" in p.stores


def test_secret_suffix_and_copy_buttons(window, qapp):
    open_new(window)
    page = window.pages[4]
    window.nav.setCurrentRow(4)
    page.yes_radio.setChecked(True)
    page.suffix.setValue(3)
    assert page.name_fields["key_alias"].value() == "ANDROID_RELEASE_KEY_ALIAS_3"
    assert window.ctx.profile.secret_use_suffix and window.ctx.profile.secret_suffix == 3
    page.copy_all_btn.click()
    assert QGuiApplication.clipboard().text().splitlines() == [
        "ANDROID_RELEASE_KEYSTORE_BASE64_3", "ANDROID_RELEASE_KEYSTORE_PASSWORD_3",
        "ANDROID_RELEASE_KEY_ALIAS_3", "ANDROID_RELEASE_KEY_PASSWORD_3"]
    page.name_fields["key_password"].copy_btn.click()
    assert QGuiApplication.clipboard().text() == "ANDROID_RELEASE_KEY_PASSWORD_3"
    assert "ANDROID_RELEASE_KEYSTORE_PASSWORD_3" in window.pages[5].text.toPlainText()


def test_generate_identity_in_background_and_copy_secret(window, qapp, monkeypatch, keytool_tools):
    open_new(window)
    window.nav.setCurrentRow(3)
    page = window.pages[3]
    monkeypatch.setattr(dialogs.GenerateIdentityDialog, "exec", lambda self: dialogs.GenerateIdentityDialog.Accepted)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)  # skip "back up now?"
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    page.generate()
    assert window.ctx.busy
    wait_until(qapp, lambda: not window.ctx.busy)
    timer.stop()
    assert len(ticks) > 3, "UI event loop was blocked during key generation"

    rec = window.ctx.identity()
    assert rec is not None and window.ctx.store.load(window.ctx.profile.id).android_identity_id == rec.id
    assert "not backed up" in page.status.text()
    assert page.v_sha256.value() == rec.fingerprint_sha256

    creds = window.ctx.vault.credentials(rec.id)
    assert creds.store_password not in page.store_pw.edit.text()     # not loaded until requested
    page.store_pw.copy_btn.click()
    assert QGuiApplication.clipboard().text() == creds.store_password
    assert creds.store_password not in window.pages[5].text.toPlainText()
    assert rec.fingerprint_sha256 in window.pages[5].text.toPlainText()


def test_import_error_is_displayed(window, qapp, monkeypatch, keytool_tools, tmp_path):
    open_new(window)
    page = window.pages[3]
    junk = tmp_path / "junk.jks"
    junk.write_bytes(b"not a keystore")
    monkeypatch.setattr(dialogs.ImportKeystoreDialog, "exec", lambda self: dialogs.ImportKeystoreDialog.Accepted)
    monkeypatch.setattr(dialogs.ImportKeystoreDialog, "values",
                        lambda self: dict(path=junk, store_password="pw123456", alias="a", key_password="pw123456"))
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()))
    page.import_keystore()
    wait_until(qapp, lambda: not window.ctx.busy)
    assert shown and ("keystore" in shown[0].lower() or "password" in shown[0].lower())
    assert window.ctx.identity() is None


def test_close_blocked_while_busy(window, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    window.ctx.begin_busy("x")
    assert not window.close()
    window.ctx.end_busy()
