#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install into the local Krita resource directory, preserving previous files."""
import argparse
import datetime
import os
from pathlib import Path
import re
import shutil


def main():
    parser = argparse.ArgumentParser(description="Instala o plugin Linework no Krita.")
    parser.add_argument("--resources", type=Path, help="Pasta de recursos personalizada do Krita")
    parser.add_argument("--enable", action="store_true", help="Ativa o plugin para a próxima abertura do Krita")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home()/".config")))/"kritarc"
    contents = config.read_text(encoding="utf-8") if config.exists() else ""
    match = re.search(r"(?m)^ResourceDirectory=(.+)$", contents)
    resources = args.resources or (Path(match.group(1)) if match else
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home()/".local/share")))/"krita")
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
    print("Instalado em:", destination)
    print("Abra o Krita. Se ele já estava aberto, feche e abra novamente.")
    print("Ativação manual: Configurações > Configurar Krita > Gerenciador de plugins Python > Linework.")
    print("Uso: selecione Linework Brush na barra; controles em Opções da ferramenta.")


if __name__ == "__main__":
    main()
