"""Regression checks for the download entry point, not application media code."""
import itertools
from pathlib import Path
import re
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def publication():
    return (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8').split('  publish:\n', 1)[1]


@pytest.mark.parametrize('results', tuple(itertools.product(('success', 'failure', 'cancelled', 'skipped'), repeat=3)))
def test_release_requires_every_native_build_to_succeed(results):
    expression = re.search(r'^    if: (.+)$', publication(), re.M)[1]
    expression = expression.replace('${{', '').replace('}}', '').strip()
    expression = expression.replace('always()', 'True').replace('github.event_name', 'event')
    expression = re.sub(r'needs\.(windows|macos|linux)\.result', r'status["\1"]', expression)
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    status = dict(zip(('windows', 'macos', 'linux'), results))
    for event in ('push', 'workflow_dispatch', 'pull_request'):
        actual = eval(expression, {'__builtins__': {}}, {'event': event, 'status': status})
        assert bool(actual) == (event == 'push' and all(value == 'success' for value in results))


def release_version_code():
    block = re.search(r'(?ms)^      - name: Derive release from app version\n.*?^        run: \|\n(.*?)(?=^      -|\Z)', publication())[1]
    shell = textwrap.dedent(block).strip().splitlines()
    assert shell[0] == "python3 - <<'PY'" and shell[-1] == 'PY'
    return '\n'.join(shell[1:-1])


def existing_tag(monkeypatch, commit=None, returncode=None):
    calls = []
    def lookup(args, **kwargs):
        calls.append(args)
        code = returncode if returncode is not None else (0 if commit else 1)
        return subprocess.CompletedProcess(args, code, (commit or '')+'\n', '')
    monkeypatch.setattr(subprocess, 'run', lookup)
    return calls


@pytest.mark.parametrize('version,tag', [('1.1.0+files.9', 'v1.1.0-files.9'), ('2.3.4', 'v2.3.4')])
def test_release_tag_follows_literal_app_version(tmp_path, monkeypatch, version, tag):
    (tmp_path / 'dragshift').mkdir()
    (tmp_path / 'dragshift/__init__.py').write_text(f'__version__ = {version!r}\n', encoding='utf-8')
    output = tmp_path / 'output'
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('GITHUB_SHA', 'a'*40)
    existing_tag(monkeypatch)
    exec(compile(release_version_code(), 'workflow-release-version', 'exec'), {})
    values = dict(line.split('=', 1) for line in output.read_text(encoding='utf-8').splitlines())
    assert values == {'version': version, 'tag': tag, 'name': f'DragShift {version}'}


def test_version_extraction_never_executes_application_code(tmp_path, monkeypatch):
    (tmp_path / 'dragshift').mkdir()
    (tmp_path / 'dragshift/__init__.py').write_text(
        "__version__ = __import__('pathlib').Path('executed').write_text('unsafe')\n", encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    with pytest.raises((ValueError, SystemExit)):
        exec(compile(release_version_code(), 'workflow-release-version', 'exec'), {})
    assert not (tmp_path / 'executed').exists() and not (tmp_path / 'output').exists()


@pytest.mark.parametrize('tag_commit,accepted', [('a'*40, True), ('b'*40, False)])
def test_existing_version_tag_allows_only_same_commit_retries(tmp_path, monkeypatch, tag_commit, accepted):
    (tmp_path / 'dragshift').mkdir()
    (tmp_path / 'dragshift/__init__.py').write_text("__version__ = '1.1.0+files.9'\n", encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    monkeypatch.setenv('GITHUB_SHA', 'a'*40)
    calls = existing_tag(monkeypatch, tag_commit)
    if accepted:
        exec(compile(release_version_code(), 'workflow-release-version', 'exec'), {})
        assert 'tag=v1.1.0-files.9' in (tmp_path / 'output').read_text(encoding='utf-8')
    else:
        with pytest.raises(SystemExit, match='Bump the application version'):
            exec(compile(release_version_code(), 'workflow-release-version', 'exec'), {})
        assert not (tmp_path / 'output').exists()
    assert calls == [['git', 'rev-parse', '--verify', '--quiet', 'refs/tags/v1.1.0-files.9^{commit}']]


def test_tag_lookup_failure_stops_publication(tmp_path, monkeypatch):
    (tmp_path / 'dragshift').mkdir()
    (tmp_path / 'dragshift/__init__.py').write_text("__version__ = '1.1.0+files.9'\n", encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    monkeypatch.setenv('GITHUB_SHA', 'a'*40)
    existing_tag(monkeypatch, returncode=128)
    with pytest.raises(SystemExit, match='Could not verify'):
        exec(compile(release_version_code(), 'workflow-release-version', 'exec'), {})
    assert not (tmp_path / 'output').exists()


def test_publication_pins_tag_source_and_requires_complete_assets():
    text = publication()
    assert 'ref: ${{ github.sha }}' in text
    assert 'fetch-depth: 0' in text
    assert text.count('uses: softprops/action-gh-release@v2') == 1
    assert 'tag_name: ${{ steps.release.outputs.tag }}' in text
    assert 'name: ${{ steps.release.outputs.name }}' in text
    assert 'target_commitish: ${{ github.sha }}' in text and 'make_latest: true' in text
    assert 'fail_on_unmatched_files: true' in text
    for name in ('DragShift-Setup.exe', 'DragShift.exe', 'DragShift-linux-amd64.deb',
                 'DragShift-mac-apple-silicon.dmg', 'DragShift-mac-intel.dmg'):
        assert f'            out/{name}' in text
    assert 'tag_name: latest' not in text and 'macOS 11+' not in text
    assert 'raw.githubusercontent.com/llamaboi55' not in text
    assert 'body_path: release-body.md' in text and 'generate_release_notes: true' in text
    assert 'packaging/release_notes.py' in text and '--version' in text and '--commit "$GITHUB_SHA"' in text


def test_mac_installer_downloads_this_fork():
    script = (ROOT / 'install-mac.sh').read_text(encoding='utf-8')
    assert 'REPO="Vokanzaa/DragShift"' in script
    assert 'https://github.com/$REPO/releases/latest/download/$ASSET' in script
    assert 'raw.githubusercontent.com/llamaboi55' not in script
    assert 'https://raw.githubusercontent.com/Vokanzaa/DragShift/main/install-mac.sh' in script
