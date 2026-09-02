from curvemole.gui.updates import asset_suffix, semantic_version, should_notify, update_kind


def test_semantic_version_and_update_kind() -> None:
    current = semantic_version("0.8.5")
    assert current == (0, 8, 5)
    assert semantic_version("v0.8.6") == (0, 8, 6)
    assert semantic_version("not-a-version") is None

    assert update_kind(current, (0, 8, 6)) == "patch"
    assert update_kind(current, (0, 9, 0)) == "minor"
    assert update_kind(current, (1, 0, 0)) == "major"


def test_automatic_notification_is_once_per_release() -> None:
    assert should_notify("0.9.0", "0.8.5")
    assert not should_notify("0.9.0", "0.9.0")


def test_self_update_asset_suffixes() -> None:
    assert asset_suffix("Linux", "x86_64") == "-linux-x86_64.AppImage"
    assert asset_suffix("Windows", "AMD64") == "-windows-x86_64.exe"
    assert asset_suffix("Darwin", "arm64") is None
    assert asset_suffix("Linux", "aarch64") is None
