"""Build version-specific update notes and exact native download links."""
import argparse
from pathlib import Path
import re


def compose(root,version,tag,commit,repository='Vokanzaa/DragShift'):
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:\+files\.\d+)?',version):raise ValueError('Invalid application version')
    if tag!='v'+version.replace('+','-',1):raise ValueError('Release tag does not match application version')
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Invalid source commit')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Invalid repository')
    notes=(Path(root)/'RELEASE_NOTES.md').read_text(encoding='utf8').strip()
    header,_,body=notes.partition('\n')
    if header.strip()!='# '+version or not body.strip():
        raise ValueError('Update RELEASE_NOTES.md for this application version before publishing')
    base=f'https://github.com/{repository}'
    download=f'{base}/releases/download/{tag}/'
    links='\n'.join(f'- [{label}]({download}{name})' for label,name in (
        ('Установщик Windows x64 · Русский / English','DragShift-Setup.exe'),
        ('Переносимая Windows-версия','DragShift.exe'),
        ('Mac Apple Silicon','DragShift-mac-apple-silicon.dmg'),
        ('Intel Mac','DragShift-mac-intel.dmg'),
        ('Linux Debian/Ubuntu x64','DragShift-linux-amd64.deb')))
    return f'''## DragShift {version}

{body.strip()}

### Готовые приложения

{links}

Пакеты включают Python/Qt и необходимые движки. macOS проверена на версии 15; подпись ad-hoc, нотариализация Apple пока не настроена.

**Source code:** ZIP/TAR в разделе Assets содержат исходники именно этого выпуска. Для установки выберите пакет своей системы.

Собрано из коммита [{commit[:7]}]({base}/commit/{commit}) после успешных проверок всех четырёх нативных сборок.
'''


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('version','tag','commit','repository','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    Path(args.output).write_text(compose(Path(__file__).resolve().parents[1],args.version,args.tag,args.commit,args.repository),encoding='utf8')
