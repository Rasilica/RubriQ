import time
from pathlib import Path

import pytest

from submission.conversion_contracts import ConversionError
from submission.hancom_profile import copy_profile, seal_profile


def profile_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    profile = tmp_path / "template"
    extension = profile / "user/uno_packages/cache/uno_packages/package/H2Orestart.oxt"
    extension.mkdir(parents=True)
    _ = (extension / "H2Orestart.jar").write_bytes(b"fixture-jar")
    _ = (extension / "description.xml").write_text(
        """<description xmlns="http://openoffice.org/extensions/description/2006">
<version value="0.7.14"/>
<identifier value="ebandal.libreoffice.H2Orestart"/></description>"""
    )
    soffice = tmp_path / "soffice"
    _ = soffice.write_bytes(b"fixture-renderer")
    java = tmp_path / "jdk"
    (java / "bin").mkdir(parents=True)
    (java / "lib/server").mkdir(parents=True)
    _ = (java / "bin/java").write_bytes(b"fixture-java")
    _ = (java / "lib/server/libjvm.dylib").write_bytes(b"fixture-jvm")
    _ = (java / "release").write_bytes(b'JAVA_VERSION="17"')
    return profile, soffice, java


def test_profile_seal_is_deterministic(tmp_path: Path) -> None:
    template, soffice, java = profile_fixture(tmp_path)

    first = seal_profile(template, soffice, java)
    second = seal_profile(template, soffice, java)

    assert first == second
    assert first.extension_version == "0.7.14"


@pytest.mark.parametrize("entry", [".lock", "user/.lock"])
def test_locked_profile_is_rejected(tmp_path: Path, entry: str) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    _ = (template / entry).write_text("active")

    with pytest.raises(ConversionError, match="invalid_config"):
        _ = seal_profile(template, soffice, java)


def test_profile_tampering_fails_before_copy(tmp_path: Path) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    provision = seal_profile(template, soffice, java)
    _ = (template / "user/added").write_text("change")

    with pytest.raises(ConversionError, match="invalid_config"):
        _ = copy_profile(provision, tmp_path / "job", time.monotonic() + 30)


def test_symlink_profile_entry_is_rejected(tmp_path: Path) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    (template / "user/escape").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ConversionError, match="invalid_config"):
        _ = seal_profile(template, soffice, java)


def test_copy_applies_private_security_settings(tmp_path: Path) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    provision = seal_profile(template, soffice, java)

    copied = copy_profile(provision, tmp_path / "job", time.monotonic() + 30)

    assert copied != template
    assert (copied / "user/registrymodifications.xcu").is_file()
    assert not (template / "user/registrymodifications.xcu").exists()


def test_expired_copy_deadline_is_rejected(tmp_path: Path) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    provision = seal_profile(template, soffice, java)

    with pytest.raises(ConversionError, match="conversion_timeout"):
        _ = copy_profile(provision, tmp_path / "job", time.monotonic() - 1)


@pytest.mark.parametrize("limit_name", ["MAX_ENTRIES", "MAX_FILE_BYTES", "MAX_PROFILE_BYTES"])
def test_profile_budget_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit_name: str
) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    monkeypatch.setattr(f"submission.hancom_profile.{limit_name}", 1)

    with pytest.raises(ConversionError, match="invalid_config"):
        _ = seal_profile(template, soffice, java)


@pytest.mark.parametrize("mode", ["missing", "version", "xml", "duplicate", "root-link"])
def test_invalid_template_is_rejected(tmp_path: Path, mode: str) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    extension = template / "user/uno_packages/cache/uno_packages/package/H2Orestart.oxt"
    if mode == "missing":
        (extension / "H2Orestart.jar").unlink()
    if mode == "version":
        _ = (extension / "description.xml").write_text("<description/>")
    if mode == "xml":
        _ = (extension / "description.xml").write_text("<broken")
    if mode == "duplicate":
        duplicate = template / "extra/H2Orestart.oxt"
        duplicate.mkdir(parents=True)
        _ = (duplicate / "H2Orestart.jar").write_bytes(b"extra")
    if mode == "root-link":
        link = tmp_path / "linked"
        link.symlink_to(template, target_is_directory=True)
        template = link

    with pytest.raises(ConversionError, match="invalid_config"):
        _ = seal_profile(template, soffice, java)


def test_missing_runtime_is_rejected(tmp_path: Path) -> None:
    template, soffice, java = profile_fixture(tmp_path)
    (java / "bin/java").unlink()

    with pytest.raises(ConversionError, match="invalid_config"):
        _ = seal_profile(template, soffice, java)
