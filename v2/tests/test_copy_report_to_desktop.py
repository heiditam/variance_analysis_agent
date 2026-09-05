import os

from agent import copy_report_to_desktop


def test_copies_report_to_desktop_dir(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = reports_dir / "variance_report_expenses_2025-10_vs_2025-11.xlsx"
    report.write_bytes(b"fake xlsx content")

    desktop_dir = tmp_path / "Desktop"
    result = copy_report_to_desktop(str(report), desktop_dir=str(desktop_dir))

    assert result == str(desktop_dir / report.name)
    assert os.path.isfile(result)
    assert open(result, "rb").read() == b"fake xlsx content"


def test_creates_desktop_dir_if_missing(tmp_path):
    report = tmp_path / "report.xlsx"
    report.write_bytes(b"content")
    desktop_dir = tmp_path / "does" / "not" / "exist" / "yet"

    result = copy_report_to_desktop(str(report), desktop_dir=str(desktop_dir))

    assert result == str(desktop_dir / "report.xlsx")
    assert os.path.isfile(result)


def test_returns_none_and_warns_instead_of_raising_on_failure(tmp_path, capsys):
    report = tmp_path / "report.xlsx"
    report.write_bytes(b"content")
    # A file (not a directory) at the desktop path makes os.makedirs fail.
    blocking_file = tmp_path / "blocked"
    blocking_file.write_text("x")

    result = copy_report_to_desktop(str(report), desktop_dir=str(blocking_file))

    assert result is None
    assert "could not copy report to Desktop" in capsys.readouterr().out
