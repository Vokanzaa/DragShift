"""Previewed, no-overwrite batch renames with staging, recovery and safe undo.

Only names change. These results must never use conversion's delete-output Undo.
The full recovery plan is durable before the first move. Move records are
group-synced; recovery locates actual file identities even after an unlogged move.
"""
from dataclasses import dataclass,replace
import ctypes
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
import unicodedata
import uuid

from .gif_sequence import ordered_paths
from .rename_rules import apply_rules,validate_rules
from .util import UserError

_LOCK=threading.Lock()
MAX_FILES=100_000
MAX_JOURNAL=256_000_000


class RenameCancelled(UserError):pass


@dataclass
class Entry:
    source:Path
    target:Path
    fingerprint:tuple
    error:str=''


@dataclass(frozen=True)
class Plan:
    entries:tuple

    @property
    def errors(self):return [entry.error for entry in self.entries if entry.error]

    @property
    def changed(self):return [entry for entry in self.entries if entry.source.name!=entry.target.name]


@dataclass(frozen=True)
class RenameResult:
    journal:Path
    pairs:tuple


def _key(path):
    text=unicodedata.normalize('NFC',str(path))
    return text.casefold() if os.name=='nt' or sys.platform=='darwin' else text


def fingerprint(path):
    info=Path(path).lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(Path(path),'is_junction',lambda:False)():
        raise UserError('Symbolic links and junctions are not renamed by this tool.')
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns


def valid_name(name):
    if (not isinstance(name,str) or not name or name in ('.','..') or name[-1] in ' .'
            or any(ord(c)<32 or ord(c)==127 or c in '<>:"/\\|?*' for c in name)):
        return False
    base=name.split('.',1)[0].upper()
    if base in {'CON','PRN','AUX','NUL'} or (base.startswith(('COM','LPT')) and base[3:] in '123456789¹²³' and len(base)==4):
        return False
    size=len(name.encode('utf-16-le'))//2 if os.name=='nt' else len(os.fsencode(name))
    return size<=255


def _validate(entries,*,check_fingerprints=False):
    entries=[replace(entry) for entry in entries]
    moving={_key(entry.source) for entry in entries if entry.source.name!=entry.target.name}
    folders={_key(entry.source) for entry in entries if entry.source.is_dir()}
    destinations={}
    for entry in entries:
        if entry.error:continue
        if entry.target.parent!=entry.source.parent or not valid_name(entry.target.name):
            entry.error='The generated name is invalid or moves the file to another folder.'
            continue
        if any(_key(parent) in folders for parent in entry.source.parents):
            entry.error='Rename a folder and its contained files in separate operations.'
        if check_fingerprints:
            try:
                if fingerprint(entry.source)!=entry.fingerprint:entry.error='A source changed since the preview. Preview again.'
            except (OSError,UserError):entry.error='A source changed or disappeared since the preview. Preview again.'
        key=_key(entry.target)
        if key in destinations:
            entry.error=destinations[key].error='Several files would receive the same name.'
        else:destinations[key]=entry
        if entry.source.name!=entry.target.name and os.path.lexists(entry.target) and key not in moving:
            entry.error='The target name already exists outside this rename operation.'
    return Plan(tuple(entries))


def preview(paths,rules,*,order='name',overrides=None,cancel=None):
    rules=validate_rules(rules)
    overrides=overrides or {}
    paths=list(paths)
    if len(paths)>MAX_FILES:raise UserError('Use up to 100,000 files in one rename operation.')
    unique={}
    for value in paths:
        path=Path(os.path.abspath(value))
        try:path=path.parent.resolve(strict=True)/path.name
        except OSError:pass
        # Distinct Unicode spellings can be separate files on NTFS/ext4. Never
        # silently drop one by normalizing its name during source collection.
        unique.setdefault(os.path.normcase(str(path)),path)
    try:paths=ordered_paths(unique.values(),order)
    except OSError:paths=list(unique.values())
    entries=[];folder_counts={}
    for index,path in enumerate(paths):
        _check_cancel(cancel)
        parent=_key(path.parent)
        folder_index=folder_counts.get(parent,0);folder_counts[parent]=folder_index+1
        try:
            fp=fingerprint(path)
            if not path.name:raise UserError('A drive or filesystem root cannot be renamed.')
            name=overrides[str(path)] if str(path) in overrides else apply_rules(path,index,rules,folder_index=folder_index)
            if not valid_name(name):raise UserError('The generated filename is invalid or too long.')
            entries.append(Entry(path,path.with_name(name),fp))
        except (UserError,OSError) as error:entries.append(Entry(path,path,(),str(error)))
    return _validate(entries)


def _windows_path(path):
    path=os.path.abspath(path)
    if path.startswith('\\\\?\\'):return path
    return '\\\\?\\UNC\\'+path[2:] if path.startswith('\\\\') else '\\\\?\\'+path


def move_exclusive(source,target):
    """Native rename with an atomic no-replace flag; never fall back to replace."""
    if os.name=='nt':
        function=ctypes.WinDLL('kernel32',use_last_error=True).MoveFileExW
        function.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint]
        function.restype=ctypes.c_int
        if not function(_windows_path(source),_windows_path(target),8):
            raise ctypes.WinError(ctypes.get_last_error())
        return
    library=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        function=library.renamex_np
        function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
        arguments=(os.fsencode(source),os.fsencode(target),4)  # Darwin RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(library,'renameat2'):
        function=library.renameat2
        function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        arguments=(-100,os.fsencode(source),-100,os.fsencode(target),1)  # RENAME_NOREPLACE
    else:raise UserError('This system does not provide exclusive file renaming.')
    function.restype=ctypes.c_int
    if function(*arguments):
        code=ctypes.get_errno()
        raise OSError(code,os.strerror(code),str(target))


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise RenameCancelled('Rename cancelled.')


class _Journal:
    def __init__(self,path,items=None):
        self.path=Path(path)
        if items is not None and len(json.dumps(items,ensure_ascii=False).encode('utf-8'))>64_000_000:
            raise UserError('The rename recovery plan is too large. Split the selection into smaller groups.')
        self.stream=self.path.open('xb' if items is not None else 'ab')
        self.pending=0;self.synced=time.monotonic()
        if items is not None:self.append({'type':'plan','version':1,'entries':items})

    def append(self,event):
        self.stream.write((json.dumps(event,ensure_ascii=False)+'\n').encode('utf-8'))
        self.stream.flush()
        self.pending+=1
        # The durable header lists every source/target/temp path and identity.
        # Recovery deliberately scans actual locations, so per-move fsync is
        # unnecessary. Phase boundaries and final completion always sync.
        if event.get('type') in ('plan','state') or self.pending>=128 or time.monotonic()-self.synced>=.25:
            self.sync()

    def sync(self):
        os.fsync(self.stream.fileno());self.pending=0;self.synced=time.monotonic()

    def close(self):
        try:
            if self.pending:self.sync()
        finally:self.stream.close()


def load_journal(path):
    path=Path(path)
    if path.stat().st_size>MAX_JOURNAL:raise UserError('The rename journal is too large.')
    lines=path.read_bytes().splitlines(keepends=True)
    try:
        header=json.loads(lines[0])
        if header.get('type')!='plan' or header.get('version')!=1:raise ValueError
        items=header['entries']
        if not isinstance(items,list) or len(items)>MAX_FILES:raise ValueError
        for item in items:
            if set(item)!={'source','target','temporary','fingerprint','location'}:raise ValueError
            source,target,temp=[Path(item[key]) for key in ('source','target','temporary')]
            if (not all(p.is_absolute() for p in (source,target,temp)) or target.parent!=source.parent
                    or temp.parent!=source.parent or not temp.name.startswith('.~rename-')
                    or not valid_name(target.name) or len(item['fingerprint'])!=4):raise ValueError
        state='prepared'
        for index,line in enumerate(lines[1:]):
            try:event=json.loads(line)
            except ValueError:
                if index==len(lines)-2 and not line.endswith(b'\n'):break
                raise
            if event['type']=='state':state=event['value']
            elif event['type']=='move':
                item=items[event['index']]
                item['location']=event['location']
                if 'fingerprint' in event:item['fingerprint']=event['fingerprint']
        return items,state
    except (ValueError,TypeError,KeyError,IndexError):raise UserError('The rename recovery journal is invalid.') from None


def _matches(path,expected,*,strict=False):
    try:actual=fingerprint(path)
    except (OSError,UserError):return False
    return actual==tuple(expected) if strict or not expected[1] else actual[:2]==tuple(expected[:2])


def _relocate(item,index,location,journal):
    old=Path(item[item['location']])
    new=Path(item[location])
    try:move_exclusive(old,new)
    except BaseException:
        # Some network filesystems can report failure after performing a move.
        if not os.path.lexists(old) and _matches(new,item['fingerprint']):item['location']=location
        raise
    item['location']=location
    actual=fingerprint(new)
    changed=actual!=tuple(item['fingerprint'])
    item['fingerprint']=actual
    journal.append({'type':'move','index':index,'location':location,'fingerprint':actual})
    return changed


def _rollback(items,journal):
    failures=[]
    for location,destination in (('target','temporary'),('temporary','source')):
        for index,item in reversed(list(enumerate(items))):
            if item['location']!=location:continue
            try:
                if not _matches(item[location],item['fingerprint']):raise UserError('A staged file is missing or replaced.')
                _relocate(item,index,destination,journal)
            except OSError as error:
                # Journal failure must not stop other files from being restored.
                failures.append(str(error))
            except UserError as error:failures.append(str(error))
    try:journal.append({'type':'state','value':'needs_recovery' if failures else 'rolled_back'})
    except OSError as error:failures.append(str(error))
    return failures


def execute(plan,journal_dir,*,cancel=None,progress=None):
    progress=progress or (lambda value:None)
    with _LOCK:
        if not isinstance(plan,Plan) or plan.errors:raise UserError('Resolve all preview errors before renaming.')
        checked=_validate(plan.entries,check_fingerprints=True)
        if checked.errors:raise UserError(checked.errors[0])
        changes=checked.changed
        if not changes:raise UserError('No filenames would change.')
        _check_cancel(cancel)
        folder=Path(journal_dir);folder.mkdir(parents=True,exist_ok=True)
        identifier=uuid.uuid4().hex
        items=[{'source':str(entry.source),'target':str(entry.target),
            'temporary':str(entry.source.with_name(f'.~rename-{identifier}-{index:06d}')),
            'fingerprint':entry.fingerprint,'location':'source'} for index,entry in enumerate(changes)]
        journal=_Journal(folder/(identifier+'.jsonl'),items)
        try:
            journal.append({'type':'state','value':'staging'})
            for index,item in enumerate(items):
                _check_cancel(cancel)
                if not _matches(item['source'],item['fingerprint'],strict=True):raise UserError('A source changed since the preview.')
                if _relocate(item,index,'temporary',journal):raise UserError('A source changed during renaming.')
                progress((index+1)/len(items)*.5)
            journal.append({'type':'state','value':'committing'})
            for index,item in enumerate(items):
                _check_cancel(cancel)
                if _relocate(item,index,'target',journal):raise UserError('A staged file changed during renaming.')
                progress(.5+(index+1)/len(items)*.5)
            journal.append({'type':'state','value':'applied'})
            return RenameResult(journal.path,tuple((entry.source,entry.target) for entry in changes))
        except BaseException as error:
            failures=_rollback(items,journal)
            if failures:raise UserError('Rename stopped. Some names need recovery; no files were overwritten. Journal: '+str(journal.path)) from error
            if isinstance(error,RenameCancelled):raise RenameCancelled('Rename cancelled; original names restored.') from None
            raise UserError('Rename failed; original names restored. '+str(error)) from error
        finally:journal.close()


def undo(path,journal_dir,*,cancel=None,progress=None):
    items,state=load_journal(path)
    if state!='applied':raise UserError('Only a completed rename can be undone.')
    entries=[]
    for item in items:
        target=Path(item['target'])
        if not _matches(target,item['fingerprint'],strict=True):raise UserError('A renamed file changed or disappeared. Undo was not applied.')
        entries.append(Entry(target,Path(item['source']),tuple(item['fingerprint'])))
    result=execute(_validate(entries),journal_dir,cancel=cancel,progress=progress)
    journal=_Journal(path)
    try:journal.append({'type':'state','value':'undone'})
    finally:journal.close()
    return result


def recover(path):
    """Restore an interrupted job; inspect actual file identities after a crash."""
    with _LOCK:
        items,state=load_journal(path)
        if state in ('applied','undone','rolled_back'):raise UserError('This rename does not need recovery.')
        for item in items:
            locations=[key for key in ('temporary','source','target') if _matches(item[key],item['fingerprint'])]
            if not locations:raise UserError('A recovery file is missing or was replaced. Check the journal before continuing.')
            item['location']=locations[0]
        journal=_Journal(path)
        try:
            failures=_rollback(items,journal)
            if failures:raise UserError('Recovery is incomplete. Close programs using these files and try again.')
        finally:journal.close()
    return [Path(item['source']) for item in items]
