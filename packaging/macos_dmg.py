"""Create and verify one DMG, retrying transient hdiutil resource contention.

No volumes are detached, no background processes are killed. Failed candidates
live only in a temporary directory; the final artifact is published after verify.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time


def create(source,output,volume,*,attempts=5,run=subprocess.run,sleep=time.sleep):
    source=Path(source).resolve(strict=True)
    output=Path(output).resolve()
    if not source.is_dir() or not 1<=attempts<=5 or output.suffix.lower()!='.dmg':
        raise ValueError('Choose an existing source folder and a .dmg output.')
    output.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(attempts):
        with tempfile.TemporaryDirectory(prefix='.dmg-candidate-',dir=output.parent) as temporary:
            candidate=Path(temporary)/'application.dmg'
            result=run(['hdiutil','create','-volname',str(volume),'-fs','HFS+','-srcfolder',str(source),
                        '-ov','-format','UDZO',str(candidate)],capture_output=True,text=True,timeout=600)
            if result.returncode:
                message=(result.stdout or '')+'\n'+(result.stderr or '')
                busy=any(term in message.lower() for term in ('resource busy','resource temporarily unavailable'))
                if not busy or attempt==attempts-1:
                    raise RuntimeError(f'hdiutil create failed: {message.strip()}')
                print(f'hdiutil resource contention; retry {attempt+2}/{attempts}',flush=True)
            else:
                if not candidate.is_file() or candidate.stat().st_size==0:
                    raise RuntimeError('hdiutil did not produce a complete image.')
                verified=run(['hdiutil','verify',str(candidate)],capture_output=True,text=True,timeout=300)
                if verified.returncode:
                    raise RuntimeError('DMG verification failed: '+str(verified.stderr))
                os.replace(candidate,output)
                return output
        sleep(2*(attempt+1))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--volume',default='DragShift')
    arguments=parser.parse_args()
    print(create(arguments.source,arguments.output,arguments.volume))
