"""Acceso a Excel por COM: encontrar instancias abiertas, abrir/activar libros y ejecutar la puerta de entrada del add-in."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from . import automation
from .automation import ApuriskError, Runner

#: Excel rechaza llamadas COM mientras se edita una celda o hay un cuadro de diálogo (RPC_E_CALL_REJECTED / SERVERCALL_RETRYLATER).
_BUSY = {-2147418111, -2147417846}
WORKBOOK_SUFFIXES = (".xlsx", ".xlsm", ".xlsb", ".xls")


def _modules():
    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as exc:  # pragma: no cover - solo fuera de Windows
        raise ApuriskError("unsupported_platform", "ApuRisk MCP necesita Windows con Excel y pywin32 instalado.") from exc
    pythoncom.CoInitialize()
    return pythoncom, pywintypes, win32com.client


def with_retry(action: Callable[[], Any], attempts: int = 6, delay: float = 0.5) -> Any:
    """Reintenta mientras Excel esté ocupado; si sigue ocupado lo dice con claridad."""
    _, pywintypes, _ = _modules()
    for attempt in range(attempts):
        try:
            return action()
        except pywintypes.com_error as exc:
            if exc.hresult in _BUSY and attempt < attempts - 1:
                time.sleep(delay)
                continue
            if exc.hresult in _BUSY:
                raise ApuriskError("excel_busy", "Excel está ocupado (¿hay una celda en edición o un cuadro de diálogo abierto?). Ciérralo y reintenta.") from exc
            raise


def running_apps() -> list[Any]:
    """Instancias de Excel abiertas en esta sesión, sin repetir (por identificador de ventana)."""
    pythoncom, _, client = _modules()
    apps: dict[int, Any] = {}

    def add(app: Any) -> None:
        try:
            apps.setdefault(int(app.Hwnd), app)
        except Exception:  # noqa: BLE001 - una instancia cerrándose no debe tumbar el listado
            pass

    try:
        add(client.GetActiveObject("Excel.Application"))
    except pythoncom.com_error:
        pass
    rot = pythoncom.GetRunningObjectTable()
    context = pythoncom.CreateBindCtx(0)
    for moniker in rot.EnumRunning():
        try:
            if not moniker.GetDisplayName(context, None).lower().endswith(WORKBOOK_SUFFIXES):
                continue
            workbook = client.Dispatch(rot.GetObject(moniker).QueryInterface(pythoncom.IID_IDispatch))
            add(workbook.Application)
        except Exception:  # noqa: BLE001
            continue
    return list(apps.values())


def select_app(instance: int | None = None) -> Any:
    """La instancia pedida (por ``instance``=Hwnd) o, si solo hay una, esa. Con varias y sin indicar cuál, lo pide."""
    apps = running_apps()
    if not apps:
        raise ApuriskError("excel_not_running", "No hay ningún Excel abierto. Abre uno con apurisk_open_workbook.")
    if instance is not None:
        for app in apps:
            if int(app.Hwnd) == instance:
                return app
        raise ApuriskError("instance_not_found", f"No hay un Excel con identificador {instance}. Usa apurisk_list_excel.")
    if len(apps) > 1:
        raise ApuriskError("several_instances", "Hay varios Excel abiertos: indica «instance» (ver apurisk_list_excel).")
    return apps[0]


def runner(app: Any) -> Runner:
    """Función que envía JSON a la puerta del add-in en esa instancia de Excel."""
    def run(text: str) -> str:
        try:
            return with_retry(lambda: app.Run(automation.FUNCTION_NAME, text))
        except ApuriskError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApuriskError("addin_not_loaded", "ApuRisk no responde en este Excel: el add-in no está cargado o es una versión anterior sin la puerta de automatización.") from exc

    return run


def describe(app: Any) -> dict[str, Any]:
    active = None
    try:
        active = app.ActiveWorkbook.Name
    except Exception:  # noqa: BLE001
        pass
    workbooks = [{"name": wb.Name, "path": wb.FullName, "active": wb.Name == active} for wb in app.Workbooks]
    info: dict[str, Any] = {"instance": int(app.Hwnd), "version": str(app.Version), "visible": bool(app.Visible), "workbooks": workbooks}
    try:
        info["apurisk"] = automation.status(runner(app))
    except ApuriskError as exc:
        info["apurisk"] = {"loaded": False, "reason": exc.message}
    else:
        info["apurisk"]["loaded"] = True
    return info


def open_workbook(path: str, instance: int | None = None) -> tuple[Any, Any]:
    """Abre (o activa, si ya está abierto) un libro. Sin Excel abierto, inicia uno visible."""
    full = os.path.abspath(path)
    if not os.path.isfile(full):
        raise ApuriskError("file_not_found", f"No existe el archivo {full}.")
    if not full.lower().endswith(WORKBOOK_SUFFIXES):
        raise ApuriskError("invalid_file", "Solo se abren libros de Excel (.xlsx, .xlsm, .xlsb, .xls).")
    _, _, client = _modules()
    apps = running_apps()
    app = select_app(instance) if apps else None
    if app is None:
        app = client.DispatchEx("Excel.Application")
        app.Visible = True
    for workbook in app.Workbooks:
        if os.path.normcase(workbook.FullName) == os.path.normcase(full):
            workbook.Activate()
            return app, workbook
    workbook = with_retry(lambda: app.Workbooks.Open(full))
    workbook.Activate()
    return app, workbook


def activate_workbook(app: Any, name: str) -> Any:
    for workbook in app.Workbooks:
        if workbook.Name.lower() == name.lower():
            workbook.Activate()
            return workbook
    raise ApuriskError("workbook_not_found", f"No hay un libro abierto llamado {name}.")


def load_addin(app: Any, xll_path: str) -> None:
    """Carga el .xll de ApuRisk en esa instancia (sirve cuando Excel se inició por automatización y no lo cargó)."""
    if not os.path.isfile(xll_path):
        raise ApuriskError("file_not_found", f"No existe {xll_path}.")
    if not with_retry(lambda: app.RegisterXLL(xll_path)):
        raise ApuriskError("addin_load_failed", "Excel no pudo cargar el add-in.")
