"""Native installation handoff; no forced process termination or shell commands."""
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QStandardPaths,QUrl
from PySide6.QtGui import QDesktopServices

from .updates import UpdateError,file_hash,asset_name


def installed_windows(executable=None,*,frozen=None,system=None):
    executable=Path(executable or sys.executable)
    frozen=getattr(sys,'frozen',False) if frozen is None else frozen
    return bool(frozen and (system or sys.platform)=='win32' and
                executable.name.lower()=='dragshift.exe' and (executable.parent/'_internal').is_dir() and
                (executable.parent/'unins000.exe').is_file())


def portable_windows():
    return sys.platform=='win32' and getattr(sys,'frozen',False) and not installed_windows()


def windows_tasks():
    import winreg
    result=[]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if winreg.QueryValueEx(key,'DragShift')[0]:result.append('autostart')
    except OSError:pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Classes\*\shell\DragShift'):
            result.append('contextmenu')
    except OSError:pass
    desktop=QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
    if desktop and (Path(desktop)/'DragShift.lnk').is_file():result.append('desktopicon')
    return result


@dataclass(frozen=True)
class Handoff:
    command:tuple[str,...]=()
    open_path:Path|None=None
    quit_app:bool=False


def prepare(package,release,language,*,executable=None,frozen=None,system=None,machine=None,tasks=None):
    """Recheck the completed file in a worker before starting a native installer."""
    package=Path(package)
    if package.is_symlink() or not package.is_file() or package.stat().st_size!=release.asset.size or file_hash(package)!=release.asset.sha256:
        raise UpdateError('The downloaded update failed its SHA-256 check. Try again.')
    system=system or sys.platform
    frozen=getattr(sys,'frozen',False) if frozen is None else frozen
    executable=Path(executable or sys.executable)
    installed=installed_windows(executable,frozen=frozen,system=system)
    expected=asset_name(system,machine,portable=system=='win32' and frozen and not installed)
    if release.asset.name!=expected:raise UpdateError('This update package does not match the installed application.')
    if installed:
        if release.asset.name!='DragShift-Setup.exe':raise UpdateError('This update package does not match the installed application.')
        selected=windows_tasks() if tasks is None else tasks
        if any(t not in ('autostart','contextmenu','desktopicon') for t in selected):raise ValueError('Unknown installer task')
        args=(str(package),'/SILENT','/SP-','/NORESTART','/CLOSEAPPLICATIONS',
              '/DRAGSHIFTUPDATE=1','/DIR='+str(executable.parent),'/LANG='+('ru' if language=='ru' else 'en'),
              '/TASKS='+','.join(selected),'/LOG='+str(package.with_suffix('.install.log')))
        return Handoff(command=args,quit_app=True)
    if system=='win32' and release.asset.name=='DragShift-Setup.exe':
        return Handoff(command=(str(package),))
    if system=='win32':return Handoff(open_path=package.parent,quit_app=bool(frozen))
    return Handoff(open_path=package,quit_app=bool(frozen))


def launch(handoff):
    """Call on the GUI thread, then quit gracefully only after successful launch."""
    try:
        if handoff.command:
            subprocess.Popen(list(handoff.command),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if sys.platform=='win32' else 0)
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(handoff.open_path))):
            raise OSError('Native installer could not be opened')
    except OSError as error:raise UpdateError('Could not open the installer. Open the release page or try again.') from error
    return handoff.quit_app
