"""Tests for FileBrowserDialog helper functions — no display needed."""
from __future__ import annotations

from hoverdeck.ui.dialogs.file_browser import _ext_chip, _human_size


def test_human_size_bytes():
    assert _human_size(0)    == "0 B"
    assert _human_size(512)  == "512 B"
    assert _human_size(1023) == "1023 B"


def test_human_size_kilobytes():
    assert _human_size(1024)  == "1 KB"
    assert _human_size(2048)  == "2 KB"


def test_human_size_megabytes():
    assert _human_size(1024 * 1024)     == "1 MB"
    assert _human_size(4 * 1024 * 1024) == "4 MB"


def test_human_size_gigabytes():
    assert _human_size(1024 ** 3) == "1 GB"


def test_ext_chip_uppercase():
    assert _ext_chip("document.pdf")  == "PDF"
    assert _ext_chip("archive.tar.gz") == "GZ"
    assert _ext_chip("script.py")     == "PY"


def test_ext_chip_max_4_chars():
    assert len(_ext_chip("file.html")) <= 4
    assert _ext_chip("file.html") == "HTML"


def test_ext_chip_no_extension():
    assert _ext_chip("Makefile") == ""
    assert _ext_chip("") == ""


def test_ext_chip_dots_in_name():
    assert _ext_chip("my.file.name.txt") == "TXT"
