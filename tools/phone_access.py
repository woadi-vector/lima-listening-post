"""User-run setup for private phone access. Does not change Tailscale plans."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import webbrowser


def main():
    cli=shutil.which('tailscale') or r'C:\Program Files\Tailscale\tailscale.exe'
    def command(*args):
        result=subprocess.run([cli,*args],capture_output=True,text=True,timeout=30)
        if result.returncode:raise ValueError(result.stderr.strip() or 'Tailscale setup did not complete.')
        return result.stdout
    print('Checking Tailscale sign-in...',flush=True)
    state=json.loads(command('status','--json'))
    if state.get('BackendState')!='Running':raise ValueError('Sign in to Tailscale on this computer first.')
    hostname=state['Self']['DNSName'].rstrip('.')
    owner=state['User'][str(state['Self']['UserID'])]['LoginName']
    origin='https://'+hostname
    print('Checking private sharing settings...',flush=True)
    config=json.loads(command('serve','status','--json') or '{}')
    configured_here=(config.get('Web',{}).get(hostname+':443',{}).get('Handlers',{}).get('/',{}).get('Proxy')=='http://127.0.0.1:8768')
    if config and not configured_here:
        print('An existing Tailscale Serve configuration is present. It was not replaced.')
        print('Inspect it with tailscale serve status before configuring Lima.');return
    with urllib.request.urlopen('http://127.0.0.1:8765/api/session',timeout=5) as response:
        local_token=json.load(response)['token']
    import socket
    with socket.socket() as probe:
        occupied=probe.connect_ex(('127.0.0.1',8768))==0
    if occupied:
        request=urllib.request.Request('http://127.0.0.1:8768/api/session',headers={'Host':hostname,'Tailscale-User-Login':owner})
        with urllib.request.urlopen(request,timeout=5) as response:
            if json.load(response).get('token')!=local_token:raise ValueError('Port 8768 is occupied by another service.')
    else:
        subprocess.Popen([sys.executable,'-B','-m','lima_next.phone','--origin',origin,'--login',owner],
                         cwd=Path(__file__).resolve().parents[1],
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if not configured_here:
        print('Enabling private HTTPS. If a setup link appears below, open it to enable HTTPS, then return here.',flush=True)
        result=subprocess.run([cli,'serve','--bg','http://127.0.0.1:8768'],timeout=180)
        if result.returncode:raise ValueError('Tailscale did not enable sharing. Follow its setup message, then run this launcher again.')
    else:print('Existing Lima private link retained. Gateway is ready.')
    print('Lima phone link:',origin)
    print('Sign in to Tailscale on your phone with the same account. Keep this computer awake and Lima running.')
    webbrowser.open(origin)


if __name__=='__main__':
    try:main()
    except subprocess.TimeoutExpired as error:
        output=error.stdout or error.stderr
        if output:print(output.decode(errors='replace') if isinstance(output,bytes) else output)
        print('Tailscale is still waiting. Follow any setup link above, then run the launcher again. No paid plan was selected.');sys.exit(1)
    except Exception as error:print('Phone setup:',error);sys.exit(1)
