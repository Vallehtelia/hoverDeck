"""PyInstaller build script.

  python build.py           -> dist/HoverDeck.exe        (portable single file)
  python build.py onedir    -> dist/HoverDeck/...        (folder; for the installer)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> None:
    if sys.platform != "win32":
        print("Build is Windows-only (PyInstaller + pywin32).")
        return

    import PyInstaller.__main__  # type: ignore[import-not-found]

    onedir = "onedir" in sys.argv
    fonts_src = str(ROOT / "assets" / "fonts")
    icons_src = str(ROOT / "assets" / "icons")
    icon_file = str(ROOT / "assets" / "icons" / "hoverdeck.ico")

    args = [
        str(ROOT / "main.py"),
        "--name=HoverDeck",
        "--onedir" if onedir else "--onefile",
        "--windowed",
        f"--icon={icon_file}",
        f"--add-data={fonts_src};assets/fonts",
        f"--add-data={icons_src};assets/icons",
        "--exclude-module=tests",
        "--exclude-module=pytest",
        "--distpath=dist",
        "--workpath=build_tmp",
        "--noconfirm",
        "--clean",
    ]

    print(f"Building HoverDeck ({'one-dir' if onedir else 'one-file'}) …")
    PyInstaller.__main__.run(args)

    exe = ROOT / "dist" / ("HoverDeck/HoverDeck.exe" if onedir else "HoverDeck.exe")
    if exe.exists():
        size_mb = exe.stat().st_size / 1_048_576
        print(f"\nDone: {exe}  ({size_mb:.1f} MB)")
    else:
        print("\nBuild finished — check dist/ for output.")


if __name__ == "__main__":
    main()
