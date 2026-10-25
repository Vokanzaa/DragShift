import importlib.util
from pathlib import Path
import pytest


def engine_module():
    path=Path(__file__).resolve().parents[1]/'packaging/media_engines.py'
    spec=importlib.util.spec_from_file_location('media_engines',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_engine_platform_selection():
    module = engine_module()
    assert 'windows-x86_64.zip' in module.ffglitch_url('Windows','AMD64')
    assert 'macos-x86_64.zip' in module.ffglitch_url('Darwin','x86_64')
    assert 'macos-aarch64.zip' in module.ffglitch_url('Darwin','arm64')
    assert 'linux-x86_64.zip' in module.ffglitch_url('Linux','x86_64')
    with pytest.raises(RuntimeError):
        module.ffglitch_url('Windows','arm64')


def test_linux_ffmpeg_checksum_requires_the_exact_asset_and_valid_hash():
    module=engine_module()
    digest='abcdef01'*8
    assert module.checksum_for_asset(digest+'  ffmpeg.tar.xz\n','ffmpeg.tar.xz')==digest
    assert module.checksum_for_asset(digest.upper()+' *ffmpeg.tar.xz\n','ffmpeg.tar.xz')==digest
    for text in (digest+'  another.tar.xz', 'bad  ffmpeg.tar.xz'):
        with pytest.raises(RuntimeError,match='checksum'):
            module.checksum_for_asset(text,'ffmpeg.tar.xz')


def test_windows_sevenzip_ignores_chocolatey_shim(tmp_path, monkeypatch):
    module = engine_module()
    shim = tmp_path / 'chocolatey' / 'bin' / '7z.exe'
    shim.parent.mkdir(parents=True)
    shim.touch()
    real = tmp_path / 'Program Files' / '7-Zip'
    real.mkdir(parents=True)
    for name in ('7z.exe', '7z.dll'):
        (real / name).touch()
    monkeypatch.setenv('ProgramFiles', str(real.parent))
    monkeypatch.setenv('ProgramFiles(x86)', str(tmp_path / 'absent'))
    monkeypatch.setattr(module.shutil, 'which', lambda name: str(shim))
    assert module.windows_sevenzip() == real / '7z.exe'
    (real / '7z.dll').unlink()
    with pytest.raises(RuntimeError, match='7z.dll'):
        module.windows_sevenzip()


def test_imagemagick_linker_paths_include_pkgconfig_system_dirs(monkeypatch):
    module = engine_module()
    monkeypatch.setenv('LDFLAGS', '-Wl,-dead_strip')
    calls = []
    monkeypatch.setattr(module, 'run', lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(module.subprocess, 'check_output',
                        lambda args, **kwargs: '/opt/homebrew/lib\n')
    env = module.imagemagick_env()
    assert calls == [['pkg-config', '--print-errors', '--exists',
                      'lqr-1 >= 0.1.0', 'libpng', 'glib-2.0']]
    assert env['LDFLAGS'] == '-Wl,-dead_strip -L/opt/homebrew/lib'


def test_macos_stages_full_native_ffmpeg_without_relinking():
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/build.yml').read_text(encoding='utf-8')
    macos = workflow.split('  macos:', 1)[1].split('  linux:', 1)[0]
    assert 'ffmpeg_formula: ffmpeg-full' in macos
    assert 'ffmpeg_formula: ffmpeg@7' in macos
    assert 'brew install "$FFMPEG_FORMULA"' in macos
    assert 'export PATH="$(brew --prefix "$FFMPEG_FORMULA")/bin:$PATH"' in macos
    assert macos.index('export PATH=') < macos.index('python packaging/media_engines.py --stage')
    assert 'brew link' not in macos


@pytest.mark.parametrize('kind,missing', [('encoders', 'libvorbis'), ('encoders', 'libvpx-vp9'),
    ('encoders', 'libmp3lame'), ('decoders', 'libvpx-vp9'), ('filters', 'loudnorm'),
    ('filters', 'acrossfade'), ('filters', 'acrusher')])
def test_required_ffmpeg_capability_gate_rejects_incomplete_build(monkeypatch, kind, missing):
    from dragshift import audio
    module = engine_module()
    required = module.required_capabilities()['ffmpeg']
    def available(requested, name='ffmpeg'):
        result = required[requested]
        return result - {missing} if requested == kind else result
    monkeypatch.setattr(audio, 'engine_capabilities', available)
    with pytest.raises(RuntimeError, match=missing):
        module.check_media_capabilities('ffmpeg')


def test_required_capability_gate_covers_audio_video_and_melt_recipes(monkeypatch):
    from dragshift import audio
    module = engine_module()
    required = module.required_capabilities()
    assert set(audio.AUDIO_ENCODERS.values()) <= required['ffmpeg']['encoders']
    assert {'libx264', 'libvpx-vp9', 'mpeg4', 'gif', 'png'} <= required['ffmpeg']['encoders']
    assert {'amix', 'asetnsamples', 'asplit', 'volume', 'acrusher'} <= required['ffmpeg']['filters']
    assert {'scale', 'fps', 'setsar', 'tpad', 'trim', 'concat', 'pad'} <= required['ffgac']['filters']
    monkeypatch.setattr(audio, 'engine_capabilities', lambda kind, name='ffmpeg': required[name][kind])
    assert module.check_media_capabilities('ffmpeg')
    assert module.check_media_capabilities('ffgac')
