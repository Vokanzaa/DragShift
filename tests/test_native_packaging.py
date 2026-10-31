import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name',['install-mac.sh','packaging/linux/build-deb.sh','packaging/linux/dragshift.desktop'])
def test_unix_entry_files_have_lf_line_endings(name):
    assert b'\r' not in (ROOT/name).read_bytes()


def module():
    spec=importlib.util.spec_from_file_location('macos_dmg',ROOT/'packaging/macos_dmg.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def test_dmg_retries_busy_error_and_verifies_before_publish(tmp_path):
    source=tmp_path/'input';source.mkdir()
    output=tmp_path/'release.dmg'
    calls=[];waits=[]
    def run(args,**kwargs):
        calls.append(args)
        if args[1]=='create':
            assert not output.exists()
            if len(calls)==1:return subprocess.CompletedProcess(args,1,'','hdiutil: create failed - Resource busy')
            Path(args[-1]).write_bytes(b'verified image')
        return subprocess.CompletedProcess(args,0,'ok','')
    module().create(source,output,'DragShift',run=run,sleep=waits.append)
    assert [call[1] for call in calls]==['create','create','verify']
    assert waits==[2] and output.read_bytes()==b'verified image'
    assert '-fs' in calls[0] and 'HFS+' in calls[0]
    assert not list(tmp_path.glob('.dmg-candidate-*'))


def test_dmg_does_not_retry_unrelated_failure_or_publish(tmp_path):
    source=tmp_path/'input';source.mkdir()
    output=tmp_path/'release.dmg'
    calls=[]
    def run(args,**kwargs):
        calls.append(args);return subprocess.CompletedProcess(args,1,'','permission denied')
    with pytest.raises(RuntimeError,match='permission denied'):
        module().create(source,output,'DragShift',run=run,sleep=lambda _:pytest.fail('unexpected retry'))
    assert len(calls)==1 and not output.exists()
