import importlib.util
from pathlib import Path
import pytest


def test_native_engine_platform_selection():
    path=Path(__file__).resolve().parents[1]/'packaging/media_engines.py'
    spec=importlib.util.spec_from_file_location('media_engines',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert 'windows-x86_64.zip' in module.ffglitch_url('Windows','AMD64')
    assert 'macos-x86_64.zip' in module.ffglitch_url('Darwin','x86_64')
    assert 'macos-aarch64.zip' in module.ffglitch_url('Darwin','arm64')
    assert 'linux-x86_64.zip' in module.ffglitch_url('Linux','x86_64')
    with pytest.raises(RuntimeError):
        module.ffglitch_url('Windows','arm64')
