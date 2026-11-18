"""¿Está ApuRisk instalado para este usuario? Lee las entradas ``OPEN*`` de Excel en el registro (así se cargan los .xll)."""

from __future__ import annotations

import os
import re
from typing import Iterable

#: Mismo patrón que scripts/Apurisk.Installation.psm1 del add-in.
CURRENT = re.compile(r'(?i)(?:^|[\\/"])Apurisk\.ExcelAddIn(?:64)?(?:-packed)?\.xll(?:"|\s|$)')
OLD = re.compile(r'(?i)(?:^|[\\/"])Apurisk\.Old\.ExcelAddIn(?:64)?(?:-packed)?\.xll(?:"|\s|$)')
OFFICE_VERSIONS = ("16.0", "15.0", "14.0")


def xll_path(entry: str) -> str | None:
    """Extrae la ruta del .xll de un valor ``OPEN`` (``/R "C:\\ruta\\x.xll"`` o la ruta sin comillas)."""
    match = re.search(r'"([^"]+\.xll)"', entry, re.IGNORECASE) or re.search(r'(\S+\.xll)', entry, re.IGNORECASE)
    return match.group(1) if match else None


def classify(entries: Iterable[str]) -> list[dict[str, object]]:
    found = []
    for entry in entries:
        channel = "current" if CURRENT.search(entry) else "old" if OLD.search(entry) else None
        if channel is None:
            continue
        path = xll_path(entry)
        found.append({"channel": channel, "path": path, "fileExists": bool(path and os.path.isfile(path))})
    return found


def registry_entries() -> list[str]:
    """Valores ``OPEN*`` de Excel para el usuario actual (vacío fuera de Windows)."""
    try:
        import winreg
    except ImportError:
        return []
    entries: list[str] = []
    for version in OFFICE_VERSIONS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Office\{version}\Excel\Options") as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if re.fullmatch(r"OPEN\d*", name) and isinstance(value, str):
                        entries.append(value)
        except OSError:
            continue
    return entries


def installed() -> list[dict[str, object]]:
    return classify(registry_entries())
