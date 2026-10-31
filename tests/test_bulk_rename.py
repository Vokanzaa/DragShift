from pathlib import Path
import threading

import pytest

from dragshift.rename_rules import Rule
from dragshift.util import UserError


def fixtures(tmp_path):
    paths=[tmp_path/'frame-2.txt',tmp_path/'frame-10.txt',tmp_path/'frame-1.txt']
    for index,path in enumerate(paths):path.write_bytes(f'content-{index}'.encode())
    return paths


def test_natural_preview_apply_and_undo_preserve_all_file_contents(tmp_path):
    from dragshift import bulk_rename as rename
    paths=fixtures(tmp_path)
    before={path.name:path.read_bytes() for path in paths}
    plan=rename.preview(paths,[Rule('number',{'where':'replace','pad':3})])
    assert [entry.source.name for entry in plan.entries]==['frame-1.txt','frame-2.txt','frame-10.txt']
    assert [entry.target.name for entry in plan.entries]==['001.txt','002.txt','003.txt']
    assert not plan.errors
    result=rename.execute(plan,tmp_path/'journals')
    for old,new in result.pairs:assert new.read_bytes()==before[old.name]
    rename.undo(result.journal,tmp_path/'journals')
    assert {path.name:path.read_bytes() for path in paths}==before


def test_swaps_case_only_and_unrelated_target_collision(tmp_path):
    from dragshift import bulk_rename as rename
    a,b=tmp_path/'a.txt',tmp_path/'b.txt'
    a.write_text('A');b.write_text('B')
    plan=rename.preview([a,b],[],overrides={str(a):'b.txt',str(b):'a.txt'})
    rename.execute(plan,tmp_path/'journals')
    assert a.read_text()=='B' and b.read_text()=='A'
    plan=rename.preview([a],[],overrides={str(a):'A.txt'})
    rename.execute(plan,tmp_path/'journals')
    assert (tmp_path/'A.txt').read_text()=='B'
    conflict=rename.preview([b],[],overrides={str(b):'A.txt'})
    assert conflict.errors
    with pytest.raises(UserError):rename.execute(conflict,tmp_path/'journals')
    assert b.read_text()=='A'


@pytest.mark.parametrize('failure_at',[2,5])
def test_mid_stage_or_commit_failure_rolls_back_every_name(tmp_path,monkeypatch,failure_at):
    from dragshift import bulk_rename as rename
    paths=fixtures(tmp_path);before={p.name:p.read_bytes() for p in paths}
    plan=rename.preview(paths,[Rule('insert',{'text':'new_'})])
    native=rename.move_exclusive
    calls=0
    def move(source,target):
        nonlocal calls
        calls+=1
        if calls==failure_at:raise OSError('injected rename failure')
        native(source,target)
    monkeypatch.setattr(rename,'move_exclusive',move)
    with pytest.raises(UserError,match='restored'):rename.execute(plan,tmp_path/'journals')
    assert {p.name:p.read_bytes() for p in paths}==before
    assert not list(tmp_path.glob('.~rename-*'))


def test_cancel_stale_plan_and_newly_occupied_target_are_safe(tmp_path):
    from dragshift import bulk_rename as rename
    paths=fixtures(tmp_path)
    plan=rename.preview(paths,[Rule('insert',{'text':'new_'})])
    paths[0].write_text('changed since preview')
    with pytest.raises(UserError,match='changed'):rename.execute(plan,tmp_path/'journals')
    plan=rename.preview(paths,[Rule('insert',{'text':'new_'})])
    target=plan.entries[0].target;target.write_text('unrelated')
    with pytest.raises(UserError):rename.execute(plan,tmp_path/'journals')
    assert target.read_text()=='unrelated'
    target.unlink()  # Owned fixture only.
    plan=rename.preview(paths,[Rule('insert',{'text':'new_'})])
    cancel=threading.Event()
    with pytest.raises(rename.RenameCancelled):
        rename.execute(plan,tmp_path/'journals',cancel=cancel,
                       progress=lambda value:cancel.set() if value>=.5 else None)
    assert all(path.exists() for path in paths) and not list(tmp_path.glob('.~rename-*'))


def test_invalid_names_and_selected_ancestor_overlap_block_all_changes(tmp_path):
    from dragshift import bulk_rename as rename
    folder=tmp_path/'folder';folder.mkdir()
    child=folder/'child.txt';child.write_text('keep')
    assert rename.preview([folder,child],[Rule('insert',{'text':'x'})]).errors
    for name in ('../escape.txt','CON.txt','bad?.txt','name.',''):
        assert rename.preview([child],[],overrides={str(child):name}).errors
    assert child.read_text()=='keep'


def test_native_exclusive_move_never_overwrites_existing_file(tmp_path):
    from dragshift import bulk_rename as rename
    a,b=tmp_path/'one',tmp_path/'two';a.write_text('one');b.write_text('two')
    with pytest.raises(OSError):rename.move_exclusive(a,b)
    assert a.read_text()=='one' and b.read_text()=='two'


def test_move_succeeded_then_reported_failure_is_still_rolled_back(tmp_path,monkeypatch):
    from dragshift import bulk_rename as rename
    paths=fixtures(tmp_path);before={p.name:p.read_bytes() for p in paths}
    plan=rename.preview(paths,[Rule('insert',{'text':'new_'})])
    native=rename.move_exclusive;calls=0
    def move(source,target):
        nonlocal calls
        calls+=1;native(source,target)
        if calls==4:raise OSError('network reported failure after move')
    monkeypatch.setattr(rename,'move_exclusive',move)
    with pytest.raises(UserError,match='restored'):rename.execute(plan,tmp_path/'journals')
    assert {p.name:p.read_bytes() for p in paths}==before


def test_interrupted_journal_recovers_by_actual_identity(tmp_path):
    from dragshift import bulk_rename as rename
    import json
    source=tmp_path/'original.txt';source.write_text('keep')
    temp=tmp_path/'.~rename-interrupted-000000';target=tmp_path/'changed.txt'
    item={'source':str(source),'temporary':str(temp),'target':str(target),
          'fingerprint':rename.fingerprint(source),'location':'source'}
    journal=tmp_path/'interrupted.jsonl'
    journal.write_text(json.dumps({'type':'plan','version':1,'entries':[item]})+'\n',encoding='utf-8')
    rename.move_exclusive(source,temp)
    # Simulate interruption before the move event reached the journal.
    assert rename.recover(journal)==[source]
    assert source.read_text()=='keep' and not temp.exists()
    assert rename.load_journal(journal)[1]=='rolled_back'
