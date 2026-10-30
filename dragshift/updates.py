"""Public release discovery and bounded, checksum-verified package downloads."""
from dataclasses import dataclass,replace
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import quote,urlsplit
from urllib.request import build_opener,HTTPSHandler,HTTPRedirectHandler,Request

import certifi

from .util import UserError

REPOSITORY='https://github.com/Vokanzaa/DragShift'
API='https://api.github.com/repos/Vokanzaa/DragShift/releases'
ASSETS=('DragShift-Setup.exe','DragShift.exe','DragShift-linux-amd64.deb',
        'DragShift-mac-apple-silicon.dmg','DragShift-mac-intel.dmg')
MAX_METADATA=2*1024*1024
MAX_PACKAGE=1024**3
HOSTS={'api.github.com','github.com','release-assets.githubusercontent.com',
       'objects.githubusercontent.com','github-releases.githubusercontent.com'}


class UpdateError(UserError):pass
class Cancelled(Exception):pass


def version_key(value):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[+-]files\.(\d+))?',str(value))
    if not match:raise ValueError('Unsupported release version')
    return tuple(int(value or 0) for value in match.groups())


@dataclass(frozen=True)
class Asset:
    name:str
    url:str
    size:int
    sha256:str


@dataclass(frozen=True)
class Release:
    version:str
    tag:str
    title:str
    url:str
    notes:str
    asset:Asset
    history_complete:bool=True


def asset_name(system=None,machine=None,portable=False):
    system=system or sys.platform
    machine=(machine or platform.machine()).lower()
    if system=='win32':return 'DragShift.exe' if portable else 'DragShift-Setup.exe'
    if system=='darwin' and machine in ('arm64','aarch64'):return 'DragShift-mac-apple-silicon.dmg'
    if system=='darwin' and machine in ('amd64','x86_64'):return 'DragShift-mac-intel.dmg'
    if system.startswith('linux') and machine in ('amd64','x86_64'):return 'DragShift-linux-amd64.deb'
    raise UpdateError('No update package is available for this system. Open the release page.')


def parse_release(data,current,*,system=None,machine=None,portable=False):
    if not isinstance(data,dict):raise UpdateError('The update response is invalid. Try again later.')
    if data.get('draft') or data.get('prerelease'):return None
    tag=data.get('tag_name','')
    try:
        key=version_key(tag)
        if key<=version_key(current):return None
    except ValueError:return None
    if not tag.startswith('v') or data.get('html_url')!=REPOSITORY+'/releases/tag/'+quote(tag,safe='.-'):
        raise UpdateError('The update response is invalid. Try again later.')
    assets=data.get('assets')
    if not isinstance(assets,list):raise UpdateError('The latest release is still being prepared. Try again later.')
    by_name={}
    for item in assets:
        if not isinstance(item,dict):continue
        name=item.get('name')
        if name in ASSETS:
            if name in by_name:raise UpdateError('The update response is invalid. Try again later.')
            by_name[name]=item
    if not set(ASSETS)<=by_name.keys() or any(a.get('state')!='uploaded' or not isinstance(a.get('size'),int) or a['size']<=0 for a in by_name.values()):
        raise UpdateError('The latest release is still being prepared. Try again later.')
    name=asset_name(system,machine,portable)
    item=by_name[name]
    url=REPOSITORY+'/releases/download/'+quote(tag,safe='.-')+'/'+name
    digest=item.get('digest','')
    if item.get('browser_download_url')!=url or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}',str(digest)) or item['size']>MAX_PACKAGE:
        raise UpdateError('The update package could not be verified. Open the release page.')
    version=tag.removeprefix('v').replace('-files.','+files.')
    title=str(data.get('name') or version)[:300]
    notes=str(data.get('body') or 'No release notes were provided.')[:65536]
    return Release(version,tag,title,data['html_url'],notes,Asset(name,url,item['size'],digest[7:].lower()))


def check_transport_url(url):
    try:
        parsed=urlsplit(url)
        valid=parsed.scheme=='https' and parsed.hostname in HOSTS and parsed.port in (None,443) and not parsed.username and not parsed.password and not parsed.fragment
    except ValueError:valid=False
    if not valid:raise UpdateError('The update download address is not trusted.')


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,url):
        check_transport_url(url)
        return super().redirect_request(request,fp,code,msg,headers,url)


def network():
    context=ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return build_opener(HTTPSHandler(context=context),_Redirects())


def _request(url):
    check_transport_url(url)
    return Request(url,headers={'User-Agent':'DragShift-Updater','Accept':'application/vnd.github+json',
                               'X-GitHub-Api-Version':'2022-11-28'})


def _json(opener,url):
    with opener.open(_request(url),timeout=15) as response:raw=response.read(MAX_METADATA+1)
    if len(raw)>MAX_METADATA:raise UpdateError('The update response is too large. Open the release page.')
    try:return json.loads(raw)
    except (ValueError,UnicodeError) as error:raise UpdateError('The update response is invalid. Try again later.') from error


def fetch_update(current,*,system=None,machine=None,portable=False,opener=None):
    opener=opener or network()
    try:
        try:data=_json(opener,API+'/latest')
        except HTTPError as error:
            if error.code==404:return None
            raise
        release=parse_release(data,current,system=system,machine=machine,portable=portable)
    except UpdateError:raise
    except (OSError,ValueError) as error:
        raise UpdateError('Could not check for updates. Check your connection and try again.') from error
    if release is None:return None
    entries={release.version:release}
    complete=True
    try:
        history=_json(opener,API+'?per_page=50')
        if not isinstance(history,list):raise ValueError('Invalid release history')
        for item in history:
            older=parse_release(item,current,system=system,machine=machine,portable=portable)
            if older and version_key(older.version)<=version_key(release.version):entries.setdefault(older.version,older)
        complete=len(history)<50
    except (UpdateError,OSError,ValueError):complete=False
    notes='\n\n'.join('## '+entry.title+'\n\n'+entry.notes for entry in sorted(entries.values(),key=lambda r:version_key(r.version),reverse=True))
    if len(notes)>200000:notes=notes[:200000];complete=False
    return replace(release,notes=notes,history_complete=complete)


def file_hash(path,cancel=None):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            if cancel is not None and cancel.is_set():raise Cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def prune_cache(folder,keep=None):
    """Only files named by this updater; retain the two most recent packages."""
    pattern=r'v\d+\.\d+\.\d+(?:-files\.\d+)?-[0-9a-f]{12}-(?:'+ '|'.join(re.escape(n) for n in ASSETS)+')'
    try:
        packages=[p for p in Path(folder).iterdir() if not p.is_symlink() and p.is_file() and re.fullmatch(pattern,p.name)]
        packages.sort(key=lambda p:(p==keep,p.stat().st_mtime_ns),reverse=True)
        for path in packages[2:]:
            try:
                path.unlink()
                path.with_suffix('.install.log').unlink(missing_ok=True)
            except OSError:pass
        for path in Path(folder).glob('.download-*.part'):
            if re.fullmatch(r'\.download-[a-z0-9_]{8}\.part',path.name) and not path.is_symlink() and time.time()-path.stat().st_mtime>86400:
                try:path.unlink()
                except OSError:pass
    except OSError:pass


def download(release,folder,*,opener=None,cancel=None,progress=lambda done,total:None):
    asset=release.asset
    if asset.name not in ASSETS or not 0<asset.size<=MAX_PACKAGE or not re.fullmatch('[0-9a-f]{64}',asset.sha256):
        raise UpdateError('The update package could not be verified. Open the release page.')
    version_key(release.tag)
    expected=REPOSITORY+'/releases/download/'+quote(release.tag,safe='.-')+'/'+asset.name
    if asset.url!=expected:raise UpdateError('The update download address is not trusted.')
    def check():
        if cancel is not None and cancel.is_set():raise Cancelled()
    check()
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(release.tag+'-'+asset.sha256[:12]+'-'+asset.name)
    if target.is_symlink():raise UpdateError('The update cache is not available. Open the release page.')
    prune_cache(folder,keep=target)
    if target.is_file() and target.stat().st_size==asset.size and file_hash(target,cancel)==asset.sha256:
        progress(asset.size,asset.size)
        check()
        return target
    if shutil.disk_usage(folder).free<asset.size+64*1024**2:
        raise UpdateError('There is not enough free space to download the update.')
    opener=opener or network()
    descriptor,temporary=tempfile.mkstemp(prefix='.download-',suffix='.part',dir=folder)
    os.close(descriptor)
    temporary=Path(temporary)
    digest=hashlib.sha256()
    received=0
    started=time.monotonic()
    try:
        progress(0,asset.size)
        with opener.open(_request(asset.url),timeout=15) as response,temporary.open('wb') as output:
            declared=response.headers.get('Content-Length')
            if declared is not None and int(declared)!=asset.size:raise UpdateError('The update download is incomplete. Try again.')
            while True:
                check()
                if time.monotonic()-started>3600:raise UpdateError('Could not download the update. Check your connection and try again.')
                chunk=getattr(response,'read1',response.read)(256*1024)
                if not chunk:break
                received+=len(chunk)
                if received>asset.size:raise UpdateError('The update download is incomplete. Try again.')
                output.write(chunk)
                digest.update(chunk)
                progress(received,asset.size)
        check()
        if received!=asset.size or digest.hexdigest()!=asset.sha256:
            raise UpdateError('The downloaded update failed its SHA-256 check. Try again.')
        temporary.replace(target)
        prune_cache(folder,keep=target)
        return target
    except (UpdateError,Cancelled):raise
    except (OSError,ValueError) as error:
        raise UpdateError('Could not download the update. Check your connection and try again.') from error
    finally:
        temporary.unlink(missing_ok=True)
