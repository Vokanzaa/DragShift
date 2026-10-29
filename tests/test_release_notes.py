import importlib.util
from pathlib import Path

import pytest


ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_notes',ROOT/'packaging/release_notes.py')
notes=importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


def test_release_notes_follow_tested_version_and_exact_asset_urls(tmp_path):
    (tmp_path/'RELEASE_NOTES.md').write_text('# 1.1.0+files.14\n\nNew updater behavior.\n',encoding='utf8')
    text=notes.compose(tmp_path,'1.1.0+files.14','v1.1.0-files.14','a'*40)
    assert 'New updater behavior.' in text and 'Source code' in text
    for name in ('DragShift-Setup.exe','DragShift.exe','DragShift-linux-amd64.deb','DragShift-mac-apple-silicon.dmg','DragShift-mac-intel.dmg'):
        assert f'https://github.com/Vokanzaa/DragShift/releases/download/v1.1.0-files.14/{name}' in text
    assert '/download/latest/' not in text and 'a'*40 in text


@pytest.mark.parametrize('field,value',[('version','1.1.0+files.15'),('tag','latest'),('commit','main'),('repository','other/path?secret')])
def test_mismatched_or_invalid_release_information_stops_publication(tmp_path,field,value):
    (tmp_path/'RELEASE_NOTES.md').write_text('# 1.1.0+files.14\n\nVersioned notes.\n',encoding='utf8')
    args=dict(root=tmp_path,version='1.1.0+files.14',tag='v1.1.0-files.14',commit='a'*40,repository='Vokanzaa/DragShift')
    args[field]=value
    with pytest.raises(ValueError):notes.compose(**args)


def test_current_repository_has_matching_nonempty_release_notes():
    from dragshift import __version__
    text=notes.compose(ROOT,__version__,'v'+__version__.replace('+','-',1),'b'*40)
    assert 'SHA-256' in text and 'Проверить обновления' in text
