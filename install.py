#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install into the local Krita resource directory, preserving previous files."""
import argparse
import datetime
import os
import platform
from pathlib import Path
import re
import shutil


def default_locations():
    if platform.system() == 'Windows':
        roaming = Path(os.environ.get('APPDATA', str(Path.home()/'AppData/Roaming')))
        local = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData/Local')))
        return local/'kritarc', roaming/'krita'
    return (Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'kritarc',
            Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'krita')


def main():
    parser = argparse.ArgumentParser(description="Install Krita Linework Tools.")
    parser.add_argument("--resources", type=Path, help="Custom Krita resource directory")
    parser.add_argument("--enable", action="store_true", help="Enable the plugin for the next Krita launch")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    config, default_resources = default_locations()
    contents = config.read_text(encoding="utf-8") if config.exists() else ""
    match = re.search(r"(?m)^ResourceDirectory=(.+)$", contents)
    resources = args.resources or (Path(match.group(1)) if match else default_resources)
    destination = resources/"pykrita"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for name in ("linework", "linework.desktop", "linework.action"):
        previous = destination/name
        if previous.exists():
            backup = resources/"linework-backups"/stamp/name
            backup.parent.mkdir(parents=True, exist_ok=True)
            if previous.is_dir():
                shutil.copytree(previous, backup)
                shutil.rmtree(previous)
            else:
                shutil.copy2(previous, backup)
                previous.unlink()
        if (source/name).is_dir():
            shutil.copytree(source/name, previous, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source/name, previous)
    if args.enable:
        config.parent.mkdir(parents=True, exist_ok=True)
        if config.exists():
            backup = resources/"linework-backups"/stamp/"kritarc"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config, backup)
        section = re.search(r"(?ms)^\[python\]\s*\n(.*?)(?=^\[|\Z)", contents)
        if section:
            text = section.group(1)
            if re.search(r"(?m)^enable_linework=", text):
                text = re.sub(r"(?m)^enable_linework=.*$", "enable_linework=true", text)
            else:
                text = "enable_linework=true\n"+text
            contents = contents[:section.start(1)]+text+contents[section.end(1):]
        else:
            contents = contents.rstrip()+"\n\n[python]\nenable_linework=true\n"
        temporary = config.with_name("kritarc.linework-tmp")
        temporary.write_text(contents, encoding="utf-8")
        temporary.replace(config)
    print("Installed in:", destination)
    print("Restart Krita to load the native bridge.")
    print("Manual activation: Settings > Configure Krita > Python Plugin Manager > Linework.")
    print("Select Linework Brush in the toolbox; controls appear in Tool Options.")


if __name__ == "__main__":
    main()
