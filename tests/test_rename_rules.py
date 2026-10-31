from pathlib import Path
import time

import pytest

from dragshift.util import UserError


def test_rules_are_sequential_and_preserve_extension_by_default(tmp_path):
    from dragshift.rename_rules import Rule,apply_rules
    source=tmp_path/'photo-12.JPG';source.write_text('fixture')
    rules=[Rule('replace',{'find':'photo','replace':'trip'}),Rule('case',{'mode':'upper'}),
           Rule('insert',{'text':'Check_','where':'prefix'})]
    assert apply_rules(source,0,rules)=='Check_TRIP-12.JPG'
    assert source.name=='photo-12.JPG' and source.read_text()=='fixture'


def test_numeration_template_rearrange_and_transliteration(tmp_path):
    from dragshift.rename_rules import Rule,apply_rules
    source=tmp_path/'Привет мир-42.png';source.touch()
    assert apply_rules(source,4,[Rule('template',{'text':'{parent}_{n:04}'})])==tmp_path.name+'_0005.png'
    assert apply_rules(source,1,[Rule('number',{'start':10,'step':5,'pad':4,'where':'replace'})])=='0015.png'
    assert apply_rules(source,0,[Rule('translit')])=='Privet mir-42.png'
    assert apply_rules(source,0,[Rule('rearrange',{'delimiter':'-','text':'{part2}_{part1}'})])=='42_Привет мир.png'


@pytest.mark.parametrize('kind,options,expected',[
    ('delete',{'start':2,'count':3},'a_005'),
    ('remove',{'text':'_','count':0},'abcd005'),
    ('regex',{'find':r'(\d+)','replace':r'X\1'},'abcd_X005'),
    ('padding',{'width':5},'abcd_00005'),
    ('extension',{'text':'webp'},'abcd_005.webp'),
    ('strip',{'mode':'digits'},'abcd_'),
    ('clean',{},'abcd 005'),
])
def test_individual_criteria(tmp_path,kind,options,expected):
    from dragshift.rename_rules import Rule,apply_rules
    source=tmp_path/'abcd_005.txt';source.touch()
    result=apply_rules(source,0,[Rule(kind,options)])
    assert result==expected if kind=='extension' else result==expected+'.txt'


def test_regex_timeout_and_strict_presets(tmp_path):
    from dragshift.rename_rules import Rule,apply_rules,read_preset,preset_json
    source=tmp_path/('a'*240+'!.txt');source.touch()
    start=time.monotonic()
    with pytest.raises(UserError,match='timed out'):
        apply_rules(source,0,[Rule('regex',{'find':'(a|aa)+$','replace':'x'})])
    assert time.monotonic()-start<1
    rules=[Rule('insert',{'text':'prefix_'})]
    assert read_preset(preset_json(rules))==rules
    with pytest.raises(UserError):read_preset('{"version":1,"rules":[{"kind":"script","options":{"code":"anything"}}]}')
    with pytest.raises(UserError):apply_rules(source,0,[Rule('template',{'text':'{name.__class__}'})])


def test_random_names_stay_stable_for_repeated_preview(tmp_path):
    from dragshift.rename_rules import Rule,apply_rules
    source=tmp_path/'one.txt';source.touch()
    rules=[Rule('random',{'length':12,'seed':'fixed','where':'replace'})]
    first=apply_rules(source,0,rules)
    assert first==apply_rules(source,0,rules)
    assert len(Path(first).stem)==12
