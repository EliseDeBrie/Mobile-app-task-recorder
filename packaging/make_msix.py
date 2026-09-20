"""Lay out and pack the Store build.

The Store takes an MSIX package and signs it itself, which is what makes the
Store route free: no certificate to buy. This script turns the folder build
that PyInstaller makes (`WHS_BUILD=folder`) into that package.

    WHS_BUILD=folder pyinstaller --noconfirm --clean packaging/whs-recorder.spec
    python packaging/make_msix.py --dist "dist/WHS Task Recorder" --out dist/msix

It writes a package folder (`<out>/layout`) holding the program under `app\\`,
the icons under `Assets\\` and the manifest at the root, and then packs it with
makeappx.exe from the Windows SDK into `<out>/WHS Task Recorder.msix`. Where
makeappx is not on the machine, `--no-pack` stops after the layout, which is
still worth having: the layout is what `Add-AppxPackage -Register` installs
for a local try-out.

The package identity comes from the environment, so the real values assigned
by Partner Center stay out of the source:

    MSIX_IDENTITY_NAME            e.g. 12345PublisherName.WHSTaskRecorder
    MSIX_PUBLISHER                e.g. CN=12345678-1234-1234-1234-123456789ABC
    MSIX_PUBLISHER_DISPLAY_NAME   the name shown in the Store

Unset, placeholders go in, which makeappx accepts and the Store rejects, so a
package built without them is for trying out only. The version is the
program's own, with the fourth part the Store reserves for itself left at 0.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

PLACEHOLDERS = {
    "MSIX_IDENTITY_NAME": "Placeholder.WHSTaskRecorder",
    "MSIX_PUBLISHER": "CN=Placeholder",
    "MSIX_PUBLISHER_DISPLAY_NAME": "Placeholder",
}

#: Folders the program carries but the package cannot, or need not, hold.
#: Relative to the program folder.
#:
#: A package is an OPC container, the same format as a .docx, and makeappx
#: refuses payload files that read as the container's own parts:
#: [Content_Types].xml and the _rels\.rels relationship parts. It says
#: "0x8007007b, the filename syntax is incorrect" after listing every file,
#: which names nothing. python-docx ships an unpacked copy of its default
#: document, full of exactly those, and does not read it at runtime: the
#: packed default.docx beside it is what Document() opens.
#:
#: Tcl's timezone tables are 600 files the windows never use, and their
#: names carry a "+" (GMT+10), which is one more thing for a package to
#: object to.
LEFT_OUT = (
    os.path.join("_internal", "docx", "templates", "default-docx-template"),
    os.path.join("_internal", "_tcl_data", "tzdata"),
)

#: File names the package format keeps for itself, wherever they are.
RESERVED_NAMES = {"[content_types].xml", "appxmanifest.xml", "appxblockmap.xml", "appxsignature.p7x"}

#: The pictures the manifest names, at the sizes Windows asks for them.
ASSETS = {
    "StoreLogo.png": 50,
    "Square44x44Logo.png": 44,
    "Square150x150Logo.png": 150,
}


def package_version() -> str:
    """The program's version as the four-part form a package must carry."""
    from whs_recorder import __version__

    parts = re.findall(r"\d+", __version__)[:3]
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts) + ".0"


def identity() -> dict:
    values = {}
    for key, placeholder in PLACEHOLDERS.items():
        value = os.environ.get(key, "").strip()
        values[key] = value or placeholder
    return values


def write_manifest(layout: str, version: str, values: dict) -> str:
    with open(os.path.join(HERE, "msix", "AppxManifest.xml"), encoding="utf-8") as f:
        text = f.read()
    text = (
        text.replace("__IDENTITY_NAME__", values["MSIX_IDENTITY_NAME"])
        .replace("__PUBLISHER__", values["MSIX_PUBLISHER"])
        .replace("__PUBLISHER_DISPLAY_NAME__", values["MSIX_PUBLISHER_DISPLAY_NAME"])
        .replace("__VERSION__", version)
    )
    path = os.path.join(layout, "AppxManifest.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def write_assets(layout: str) -> None:
    """The icon at each size the manifest names, drawn for that size rather
    than shrunk from one picture, so the 44px one stays readable."""
    from make_icon import draw

    folder = os.path.join(layout, "Assets")
    os.makedirs(folder, exist_ok=True)
    for name, size in ASSETS.items():
        draw(size).save(os.path.join(folder, name), format="PNG")


def drop_reserved_names(folder: str) -> list:
    """Remove payload files whose name the package format reserves, and
    return their paths relative to `folder`."""
    dropped = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.lower() in RESERVED_NAMES or name.lower().endswith(".rels"):
                path = os.path.join(root, name)
                os.remove(path)
                dropped.append(os.path.relpath(path, folder))
    return sorted(dropped)


def find_makeappx() -> str:
    """makeappx.exe from the newest Windows SDK on the machine, or ''."""
    if os.environ.get("MAKEAPPX"):
        return os.environ["MAKEAPPX"]
    found = shutil.which("makeappx")
    if found:
        return found
    roots = [
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
    ]
    candidates = []
    for root in roots:
        candidates += glob.glob(os.path.join(root, "Windows Kits", "10", "bin", "*", "x64", "makeappx.exe"))
    return max(candidates) if candidates else ""


def lay_out(dist: str, out: str) -> str:
    exe = os.path.join(dist, "WHS Task Recorder.exe")
    if not os.path.isfile(exe):
        raise SystemExit(
            f"No program at {exe}. Build the folder form first:\n"
            "  WHS_BUILD=folder pyinstaller --noconfirm --clean packaging/whs-recorder.spec"
        )
    layout = os.path.join(out, "layout")
    if os.path.isdir(layout):
        shutil.rmtree(layout)
    shutil.copytree(dist, os.path.join(layout, "app"))
    app = os.path.join(layout, "app")
    for folder in LEFT_OUT:
        if os.path.isdir(os.path.join(app, folder)):
            shutil.rmtree(os.path.join(app, folder))
            print(f"  left out {folder}\\ (see LEFT_OUT)")
    for dropped in drop_reserved_names(app):
        print(f"  left out {dropped}: the package format keeps that name for itself")
    write_assets(layout)
    version = package_version()
    values = identity()
    write_manifest(layout, version, values)

    print(f"Laid out {layout}")
    print(f"  version   {version}")
    for key, value in values.items():
        note = "  (placeholder: set the repository variable before a Store upload)" \
            if value == PLACEHOLDERS[key] else ""
        print(f"  {key:<28}{value}{note}")
    return layout


def pack(layout: str, out: str) -> str:
    makeappx = find_makeappx()
    if not makeappx:
        raise SystemExit(
            "makeappx.exe was not found. It comes with the Windows SDK; on a machine "
            "without it, run with --no-pack and keep the layout."
        )
    # Absolute, both of them: makeappx prefixes its paths with \\?\ and
    # a relative one comes out as a name Windows calls invalid (0x8007007b).
    layout = os.path.abspath(layout)
    package = os.path.abspath(os.path.join(out, "WHS Task Recorder.msix"))
    if os.path.exists(package):
        os.remove(package)
    # /o overwrites. makeappx checks the manifest against its schema and that
    # every file it names is in the folder, which is the validation the Store
    # would otherwise do on upload. Signing is not part of it: the Store does
    # that.
    subprocess.run([makeappx, "pack", "/o", "/d", layout, "/p", package], check=True)
    print(f"Packed {package} ({os.path.getsize(package) // (1024 * 1024)} MB)")
    return package


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dist", default=os.path.join("dist", "WHS Task Recorder"),
                        help="the folder PyInstaller built (default: dist/WHS Task Recorder)")
    parser.add_argument("--out", default=os.path.join("dist", "msix"),
                        help="where the layout and the package go (default: dist/msix)")
    parser.add_argument("--no-pack", action="store_true",
                        help="write the layout only; do not look for makeappx")
    args = parser.parse_args(argv)

    layout = lay_out(args.dist, args.out)
    if not args.no_pack:
        pack(layout, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
