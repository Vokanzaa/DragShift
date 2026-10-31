"""Ordered, deterministic filename rules. No executable expressions or scripts."""
from dataclasses import dataclass,field
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import random
import string
import unicodedata

from anyascii import anyascii
import regex

from .util import UserError

MAX_RULES=64
TIMEOUT=.05
SCHEMA={
 'insert':{'text','where','position','anchor'},'delete':{'start','count','from_right'},
 'remove':{'text','count','case_sensitive'},'replace':{'find','replace','count','case_sensitive'},
 'regex':{'find','replace','count','case_sensitive'},'case':{'mode'},
 'number':{'start','step','pad','where','separator','per_folder'},
 'padding':{'width'},'strip':{'mode','characters'},'clean':set(),'translit':set(),
 'template':{'text'},'rearrange':{'delimiter','text'},
 'date_reformat':{'find','input_format','output_format'},
 'random':{'length','seed','where','separator'},'extension':{'text'},'mapping':{'names'},
}


@dataclass(frozen=True)
class Rule:
    kind:str
    options:dict=field(default_factory=dict)
    scope:str='stem'
    enabled:bool=True


def _text(value,limit=4096):
    if not isinstance(value,str) or len(value)>limit:raise UserError('Enter a shorter text rule.')
    return value


def _integer(value,low,high):
    if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
        raise UserError('Choose a valid number for the rename rule.')
    return value


def validate_rules(rules):
    rules=list(rules)
    if len(rules)>MAX_RULES:raise UserError('Use up to 64 rename rules.')
    for rule in rules:
        if (not isinstance(rule,Rule) or rule.kind not in SCHEMA or not isinstance(rule.options,dict)
                or set(rule.options)-SCHEMA[rule.kind] or rule.scope not in ('stem','full','extension')
                or not isinstance(rule.enabled,bool)):
            raise UserError('Unsupported or malformed rename rule.')
    return rules


@lru_cache(maxsize=128)
def _pattern(text,sensitive=True):
    try:return regex.compile(_text(text,1024),0 if sensitive else regex.IGNORECASE)
    except regex.error as error:raise UserError('Invalid regular expression: '+str(error)) from None


class _Facts:
    def __init__(self,path,index,folder_index):
        self.path=path
        self.index=index
        self.folder_index=index if folder_index is None else folder_index
        self.cache={}
        self.is_folder=path.is_dir()

    def get(self,key,current,parts):
        path=Path(current)
        if key in ('name','stem'):return current if self.is_folder else path.stem
        if key=='full':return current
        if key=='ext':return '' if self.is_folder else path.suffix.lstrip('.')
        if key=='parent':return self.path.parent.name
        if key=='n':return self.index+1
        if key.startswith('part') and key[4:].isdigit():
            index=int(key[4:])-1
            if not 0<=index<len(parts):raise UserError('This filename does not contain the requested part.')
            return parts[index]
        if key in self.cache:return self.cache[key]
        if key in ('modified','created','size'):
            info=self.path.stat()
            if key=='size':value=info.st_size
            elif key=='modified':value=datetime.fromtimestamp(info.st_mtime)
            else:
                stamp=getattr(info,'st_birthtime',None)
                if stamp is None:raise UserError('Creation time is unavailable for this file. Use modified time instead.')
                value=datetime.fromtimestamp(stamp)
        elif key in ('width','height','date_taken'):
            from PIL import Image,ExifTags
            with Image.open(self.path) as image:
                exif=image.getexif()
                size=image.size[::-1] if exif.get(274,1) in (5,6,7,8) else image.size
                if key in ('width','height'):value=size[0 if key=='width' else 1]
                else:
                    raw=exif.get(36867) or exif.get_ifd(ExifTags.IFD.Exif).get(36867) or exif.get(306)
                    if not raw:raise UserError('This image has no capture date.')
                    value=datetime.strptime(str(raw),'%Y:%m:%d %H:%M:%S')
        elif key in ('artist','album','title','track','year'):
            from .audio import probe
            tags={str(k).lower():v for k,v in probe(self.path).tags.items()}
            value=tags.get(key,tags.get('date') if key=='year' else None)
            if value is None:raise UserError('The requested media tag is unavailable: '+key)
        else:raise UserError('Unknown filename template field: '+key)
        self.cache[key]=value
        return value


def _template(text,facts,current,parts=()):
    output=[]
    for literal,key,spec,conversion in string.Formatter().parse(_text(text)):
        output.append(literal)
        if key is None:continue
        if conversion or not key or not all(c.isalnum() or c=='_' for c in key):
            raise UserError('Use named filename fields without attributes or conversions.')
        value=facts.get(key,current,parts)
        if isinstance(value,datetime):
            if len(spec)>64 or regex.search(r'%\d',spec):raise UserError('Choose a shorter date format without numeric widths.')
            value=value.strftime(spec or '%Y-%m-%d')
        elif isinstance(value,int):
            if spec and (not regex.fullmatch(r'0?\d{1,2}d?',spec) or int(spec.rstrip('d') or '0')>12):
                raise UserError('Number padding must be between 0 and 12.')
            value=format(value,spec)
        elif spec:raise UserError('This filename field does not support a format.')
        output.append(str(value))
    return ''.join(output)


def _place(text,addition,where,separator=''):
    if where=='replace':return addition
    if where=='prefix':return addition+separator+text
    if where=='suffix':return text+separator+addition
    raise UserError('Choose prefix, suffix or replacement naming.')


def _apply(rule,text,current,facts):
    options=rule.options
    kind=rule.kind
    if kind=='insert':
        addition=_template(options.get('text',''),facts,current)
        where=options.get('where','prefix')
        if where in ('prefix','suffix'):return _place(text,addition,where)
        if where=='position':
            position=min(len(text),_integer(options.get('position',1),1,4096)-1)
        else:
            anchor=_text(options.get('anchor',''))
            if not anchor:return text
            position=text.find(anchor)
            if position<0:return text
            if where=='after':position+=len(anchor)
            elif where!='before':raise UserError('Choose a valid insertion position.')
        return text[:position]+addition+text[position:]
    if kind=='delete':
        start=_integer(options.get('start',1),1,4096)-1
        count=_integer(options.get('count',1),0,4096)
        if options.get('from_right',False):
            right=max(0,len(text)-start);left=max(0,right-count)
            return text[:left]+text[right:]
        return text[:start]+text[start+count:]
    if kind in ('replace','remove','regex'):
        find=_text(options.get('text' if kind=='remove' else 'find',''))
        if not find:return text
        replacement='' if kind=='remove' else _text(options.get('replace',''))
        pattern=_pattern(find if kind=='regex' else regex.escape(find),options.get('case_sensitive',True))
        count=_integer(options.get('count',0),0,100_000)
        return pattern.sub(replacement if kind=='regex' else lambda match:replacement,text,count=count,timeout=TIMEOUT)
    if kind=='case':
        methods={'lower':str.lower,'upper':str.upper,'title':str.title,'sentence':str.capitalize,'swap':str.swapcase}
        if options.get('mode','lower') not in methods:raise UserError('Choose a supported letter case.')
        return methods[options.get('mode','lower')](text)
    if kind=='number':
        number=_integer(options.get('start',1),-10**12,10**12)+_integer(options.get('step',1),-10**6,10**6)*(facts.folder_index if options.get('per_folder') else facts.index)
        digits=str(number).zfill(_integer(options.get('pad',3),0,12))
        return _place(text,digits,options.get('where','suffix'),_text(options.get('separator','_')))
    if kind=='padding':
        width=_integer(options.get('width',3),0,12)
        return regex.sub(r'\d+',lambda match:str(int(match[0])).zfill(width),text)
    if kind=='strip':
        mode=options.get('mode','digits')
        patterns={'digits':r'\p{N}','symbols':r'[\p{P}\p{S}]','brackets':r'[\[\](){}]','spaces':r'\s'}
        if mode=='characters':return text.translate(str.maketrans('','',_text(options.get('characters',''))))
        if mode not in patterns:raise UserError('Choose the characters to remove.')
        return regex.sub(patterns[mode],'',text)
    if kind=='clean':return regex.sub(r'[\s_.]+',' ',unicodedata.normalize('NFC',text)).strip(' ._-')
    if kind=='translit':return anyascii(text)
    if kind in ('template','rearrange'):
        parts=text.split(_text(options.get('delimiter','_'))) if kind=='rearrange' else ()
        return _template(options.get('text','{name}'),facts,current,parts)
    if kind=='date_reformat':
        pattern=_pattern(options.get('find',r'\d{4}-\d{2}-\d{2}'))
        input_format=_text(options.get('input_format','%Y-%m-%d'),64)
        output_format=_text(options.get('output_format','%d.%m.%Y'),64)
        if regex.search(r'%\d',output_format):raise UserError('Use a date format without numeric widths.')
        return pattern.sub(lambda match:datetime.strptime(match[0],input_format).strftime(output_format),text,timeout=TIMEOUT)
    if kind=='random':
        seed=_text(options.get('seed','stable'))
        generator=random.Random(hashlib.sha256((str(facts.path)+'\0'+seed).encode()).digest())
        value=''.join(generator.choice(string.ascii_letters+string.digits) for _ in range(_integer(options.get('length',8),1,32)))
        return _place(text,value,options.get('where','suffix'),_text(options.get('separator','_')))
    raise UserError('Unsupported rename rule.')


def apply_rules(path,index,rules,*,folder_index=None):
    path=Path(path)
    facts=_Facts(path,index,folder_index)
    current=path.name
    try:
        for rule in validate_rules(rules):
            if not rule.enabled:continue
            if rule.kind=='extension':
                if facts.is_folder:raise UserError('Folders do not have a file extension.')
                value=_text(rule.options.get('text',''),255).lstrip('.')
                current=Path(current).stem+('.'+value if value else '')
                continue
            if rule.kind=='mapping':
                names=rule.options.get('names',{})
                if not isinstance(names,dict):raise UserError('Choose a valid filename mapping.')
                current=_text(names.get(current,current))
                continue
            stem,suffix=(current,'') if facts.is_folder else (Path(current).stem,Path(current).suffix)
            text=current if rule.scope=='full' else suffix.lstrip('.') if rule.scope=='extension' else stem
            result=_apply(rule,text,current,facts)
            current=result if rule.scope=='full' else stem+('.'+result if result else '') if rule.scope=='extension' else result+suffix
            if len(current)>4096:raise UserError('The generated filename is too long.')
        return current
    except TimeoutError:raise UserError('The rename regular expression timed out. Simplify the pattern.') from None
    except (regex.error,ValueError,IndexError,KeyError) as error:
        raise UserError('Invalid rename rule: '+str(error)) from None


def preset_json(rules):
    from dataclasses import asdict
    return json.dumps({'version':1,'rules':[asdict(rule) for rule in validate_rules(rules)]},ensure_ascii=False,indent=2)


def read_preset(text):
    try:
        if len(text)>1_000_000:raise ValueError
        data=json.loads(text)
        if not isinstance(data,dict) or set(data)!= {'version','rules'} or type(data['version']) is not int or data['version']!=1 or not isinstance(data['rules'],list):raise ValueError
        if len(data['rules'])>MAX_RULES:raise ValueError
        return validate_rules([Rule(**item) for item in data['rules']])
    except (TypeError,ValueError,KeyError):
        raise UserError('This is not a supported rename preset.') from None
