import hashlib,io,json,threading
from pathlib import Path

import pytest

from dragshift import updates


def release_data(number=14,payload=b'installer'):
    tag=f'v1.1.0-files.{number}'
    return {'tag_name':tag,'html_url':updates.REPOSITORY+'/releases/tag/'+tag,
            'name':f'Version {number}','body':f'Changes in {number}','draft':False,'prerelease':False,
            'assets':[{'name':name,'state':'uploaded','size':len(payload),
                       'digest':'sha256:'+hashlib.sha256(payload).hexdigest(),
                       'browser_download_url':updates.REPOSITORY+'/releases/download/'+tag+'/'+name}
                      for name in updates.ASSETS]}


class Response(io.BytesIO):
    def __init__(self,data,headers=None):
        super().__init__(data)
        self.headers=headers or {}


class Opener:
    def __init__(self,*responses):self.responses=list(responses);self.requests=[]
    def open(self,request,timeout):
        self.requests.append((request.full_url,timeout))
        response=self.responses.pop(0)
        if isinstance(response,Exception):raise response
        return response


def test_numeric_versions_and_no_downgrades():
    assert updates.version_key('v1.1.0-files.10')>updates.version_key('1.1.0+files.9')
    assert updates.version_key('1.2.0')>updates.version_key('1.1.0+files.99')
    for number in (9,13):
        assert updates.parse_release(release_data(number),'1.1.0+files.13',system='win32') is None


def test_complete_stable_release_and_correct_native_asset():
    data=release_data()
    assert updates.parse_release(data,'1.1.0+files.13',system='win32').asset.name=='DragShift-Setup.exe'
    assert updates.parse_release(data,'1.1.0+files.13',system='darwin',machine='arm64').asset.name.endswith('apple-silicon.dmg')
    assert updates.parse_release(data,'1.1.0+files.13',system='darwin',machine='x86_64').asset.name.endswith('intel.dmg')
    assert updates.parse_release(data,'1.1.0+files.13',system='linux',machine='x86_64').asset.name.endswith('.deb')
    assert updates.parse_release(data,'1.1.0+files.13',system='win32',portable=True).asset.name=='DragShift.exe'
    with pytest.raises(updates.UpdateError):updates.parse_release(data,'1.1.0',system='linux',machine='arm64')
    for field in ('draft','prerelease'):
        altered=dict(data,**{field:True})
        assert updates.parse_release(altered,'1.1.0',system='win32') is None
    data['assets'].pop()
    with pytest.raises(updates.UpdateError):updates.parse_release(data,'1.1.0',system='win32')


@pytest.mark.parametrize('change',['digest','size','url','release_url','duplicate','state'])
def test_unsafe_or_incomplete_metadata_is_never_installable(change):
    data=release_data()
    asset=next(a for a in data['assets'] if a['name']=='DragShift-Setup.exe')
    if change=='digest':asset['digest']=''
    if change=='size':asset['size']=10**15
    if change=='url':asset['browser_download_url']='https://example.com/DragShift-Setup.exe'
    if change=='release_url':data['html_url']='https://github.com/other/repo/releases/tag/v1.1.0-files.14'
    if change=='duplicate':data['assets'].append(dict(asset))
    if change=='state':asset['state']='new'
    with pytest.raises(updates.UpdateError):updates.parse_release(data,'1.1.0',system='win32')


def test_fetches_accumulated_notes_without_duplicates():
    latest=release_data(16)
    transport=Opener(Response(json.dumps(latest).encode()),Response(json.dumps([latest,release_data(15),release_data(14),release_data(13)]).encode()))
    result=updates.fetch_update('1.1.0+files.13',system='win32',opener=transport)
    assert result.notes.index('Changes in 16')<result.notes.index('Changes in 15')<result.notes.index('Changes in 14')
    assert 'Changes in 13' not in result.notes and result.notes.count('Changes in 16')==1
    assert result.history_complete and len(transport.requests)==2
    same=Opener(Response(json.dumps(latest).encode()))
    assert updates.fetch_update('1.1.0+files.16',system='win32',opener=same) is None
    assert len(same.requests)==1


def test_history_failure_keeps_current_release_with_explicit_limit():
    transport=Opener(Response(json.dumps(release_data()).encode()),OSError('offline'))
    result=updates.fetch_update('1.1.0+files.13',system='win32',opener=transport)
    assert result.version=='1.1.0+files.14' and not result.history_complete


def test_download_is_streamed_verified_atomic_and_reusable(tmp_path):
    payload=b'payload'*100000
    release=updates.parse_release(release_data(payload=payload),'1.1.0',system='win32')
    progress=[]
    transport=Opener(Response(payload,{'Content-Length':str(len(payload))}))
    out=updates.download(release,tmp_path,opener=transport,progress=lambda a,b:progress.append((a,b)))
    assert out.read_bytes()==payload and len(progress)>2
    assert not list(tmp_path.glob('*.part'))
    assert updates.download(release,tmp_path,opener=Opener())==out
    out.write_bytes(b'corrupt cache')
    assert updates.download(release,tmp_path,opener=Opener(Response(payload))).read_bytes()==payload


@pytest.mark.parametrize('reason',['hash','truncated','too_long','cancel','network','content_length'])
def test_bad_download_never_publishes_an_executable(tmp_path,reason):
    payload=b'payload'*100000
    release=updates.parse_release(release_data(payload=payload),'1.1.0',system='win32')
    cancel=threading.Event()
    received=payload
    headers={}
    if reason=='hash':received=b'X'*len(payload)
    if reason=='truncated':received=payload[:-1]
    if reason=='too_long':received=payload+b'!'
    if reason=='content_length':headers={'Content-Length':'1'}
    response=OSError('offline') if reason=='network' else Response(received,headers)
    def progress(a,b):
        if reason=='cancel' and a:cancel.set()
    with pytest.raises((updates.UpdateError,updates.Cancelled)):
        updates.download(release,tmp_path,opener=Opener(response),cancel=cancel,progress=progress)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('url',['http://github.com/file','https://github.com.evil.test/file','https://user@github.com/file','https://github.com:444/file','file:///C:/payload.exe'])
def test_redirects_are_https_and_github_only(url):
    with pytest.raises(updates.UpdateError):updates.check_transport_url(url)


def test_metadata_size_and_invalid_json_are_bounded():
    for body in (b'not json',b' '* (updates.MAX_METADATA+1)):
        with pytest.raises(updates.UpdateError):
            updates.fetch_update('1.1.0',system='win32',opener=Opener(Response(body)))


def test_download_uses_available_bytes_instead_of_waiting_for_full_chunks(tmp_path):
    class Available(Response):
        def read(self,*a):raise AssertionError('A full blocking read would delay cancellation')
        def read1(self,n):return io.BytesIO.read(self,min(n,1000))
    payload=b'content'*1000
    release=updates.parse_release(release_data(payload=payload),'1.1.0',system='win32')
    assert updates.download(release,tmp_path,opener=Opener(Available(payload))).read_bytes()==payload


def test_cache_cleanup_keeps_two_packages_and_ignores_unrelated_files(tmp_path):
    import os,time
    files=[]
    for n in range(4):
        p=tmp_path/f'v1.1.0-files.{n}-aaaaaaaaaaaa-DragShift-Setup.exe'
        p.write_bytes(b'control')
        os.utime(p,(100+n,100+n))
        files.append(p)
    unrelated=tmp_path/'user-file.exe'
    unrelated.write_bytes(b'keep')
    stale=tmp_path/'.download-stale000.part'
    stale.touch()
    os.utime(stale,(time.time()-90000,time.time()-90000))
    active=tmp_path/'.download-active00.part'
    active.touch()
    updates.prune_cache(tmp_path,keep=files[0])
    assert files[0].exists() and files[3].exists()
    assert not files[1].exists() and not files[2].exists()
    assert unrelated.read_bytes()==b'keep' and active.exists() and not stale.exists()
