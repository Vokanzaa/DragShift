from pathlib import Path

import pytest

from dragshift import update_install as install,updates
from test_updates import release_data


def package(tmp_path,name='DragShift-Setup.exe'):
    result=updates.parse_release(release_data(),'1.1.0',system='win32',portable=name=='DragShift.exe')
    file=tmp_path/name
    file.write_bytes(b'installer')
    return file,result


def test_windows_update_preserves_destination_language_and_actual_tasks(tmp_path):
    exe=tmp_path/'custom path'/'DragShift.exe'
    (exe.parent/'_internal').mkdir(parents=True)
    (exe.parent/'unins000.exe').touch()
    file,release=package(tmp_path)
    handoff=install.prepare(file,release,'ru',executable=exe,frozen=True,system='win32',tasks=['contextmenu'])
    assert handoff.quit_app and '/DRAGSHIFTUPDATE=1' in handoff.command
    assert '/DIR='+str(exe.parent) in handoff.command and '/LANG=ru' in handoff.command
    assert '/TASKS=contextmenu' in handoff.command and '/NORESTART' in handoff.command
    assert not any('taskkill' in part for part in handoff.command)
    empty=install.prepare(file,release,'en',executable=exe,frozen=True,system='win32',tasks=[])
    assert '/TASKS=' in empty.command


def test_source_portable_mac_and_linux_use_explicit_native_routes(tmp_path):
    file,release=package(tmp_path)
    assert not install.prepare(file,release,'en',frozen=False,system='win32').quit_app
    portable,portable_release=package(tmp_path,'DragShift.exe')
    p=install.prepare(portable,portable_release,'en',frozen=True,system='win32')
    assert p.open_path==tmp_path and p.quit_app and not p.command
    for system in ('darwin','linux'):
        native=updates.parse_release(release_data(),'1.1.0',system=system,machine='x86_64')
        native_file=tmp_path/native.asset.name
        native_file.write_bytes(b'installer')
        p=install.prepare(native_file,native,'en',frozen=True,system=system,machine='x86_64')
        assert p.open_path==native_file and p.quit_app
        with pytest.raises(updates.UpdateError):install.prepare(file,release,'en',frozen=True,system=system,machine='x86_64')


def test_tampered_cache_never_reaches_native_launcher(tmp_path):
    file,release=package(tmp_path)
    file.write_bytes(b'tampered!')
    with pytest.raises(updates.UpdateError):install.prepare(file,release,'en')


def test_failed_native_launch_does_not_request_app_exit(monkeypatch):
    def fail(*a,**k):raise OSError('test launch failure')
    monkeypatch.setattr(install.subprocess,'Popen',fail)
    with pytest.raises(updates.UpdateError):install.launch(install.Handoff(command=('missing.exe',),quit_app=True))
    monkeypatch.setattr(install.QDesktopServices,'openUrl',lambda _:False)
    with pytest.raises(updates.UpdateError):install.launch(install.Handoff(open_path=Path('/missing.deb'),quit_app=True))


def test_update_mode_skips_language_rewrite_and_relaunches_only_after_install():
    script=(Path(__file__).resolve().parents[1]/'installer/DragShift.iss').read_text(encoding='utf8')
    language_line=next(line for line in script.splitlines() if 'ValueName: "language"' in line)
    assert 'Check: not IsUpdateInstall' in language_line
    assert 'Parameters: "--quiet"; Flags: nowait; Check: IsUpdateInstall' in script
