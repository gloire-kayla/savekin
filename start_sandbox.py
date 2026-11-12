"""Interactive sandbox launcher; does not depend on PowerShell script execution policy."""
import argparse
import ctypes
from ctypes import wintypes
import getpass
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import urllib.request
import warnings
import sandbox_check

ROOT=Path(__file__).resolve().parent
KEYS=('PAYMENT_MODE','PAYPAL_CLIENT_ID','PAYPAL_CLIENT_SECRET','PAYPAL_TREASURER_EMAIL','PAYPAL_WEBHOOK_ID')

def running():
    try:
        with socket.create_connection(('127.0.0.1',8000),timeout=2): return True
    except ConnectionRefusedError: return False
    except TimeoutError:
        if os.name!='nt': raise
        # Windows can time out instead of refusing a connection after Ctrl+C.
        # Check listeners, including wildcard bindings, before treating it as free.
        output=subprocess.check_output(['netstat','-ano','-p','tcp'],text=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return bool(re.search(r'^\s*TCP\s+\S+:8000\s+\S+\s+LISTENING\s+\d+\s*$',output,re.MULTILINE))

def listener_pid():
    output=subprocess.check_output(['netstat','-ano','-p','tcp'],text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    matches=re.findall(r'^\s*TCP\s+127\.0\.0\.1:8000\s+\S+\s+LISTENING\s+(\d+)\s*$',output,re.MULTILINE)
    if len(matches)!=1: raise RuntimeError('Could not identify one local server. Stop the backend manually.')
    return int(matches[0])

def stop_verified_server():
    if os.name!='nt': raise RuntimeError('Automatic restart is supported on Windows only. Stop the backend manually.')
    with urllib.request.urlopen('http://127.0.0.1:8000/app.js',timeout=4) as response:
        if response.read()!=(ROOT/'web'/'app.js').read_bytes():
            raise RuntimeError('Port 8000 does not match this SaveKin checkout. No process was stopped.')
    pid=listener_pid()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype=wintypes.BOOL
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.TerminateProcess.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1001,False,pid)  # Query limited information + terminate this verified process.
    if not handle: raise RuntimeError('Cannot access the local backend. Stop it manually before retrying.')
    try:
        buffer=ctypes.create_unicode_buffer(32768); size=wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
            raise RuntimeError('Cannot verify the backend executable. No process was stopped.')
        if not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?\.exe',Path(buffer.value).name,re.IGNORECASE) or listener_pid()!=pid:
            raise RuntimeError('Backend identity changed. No process was stopped.')
        if not kernel.TerminateProcess(handle,0): raise RuntimeError('Could not stop the verified backend.')
    finally:
        kernel.CloseHandle(handle)

def validate_credentials(environment):
    previous={key:os.environ.get(key) for key in KEYS}
    try:
        for key in KEYS: os.environ[key]=environment.get(key,'')
        return sandbox_check.check()
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value

def main(argv=None):
    parser=argparse.ArgumentParser(description='Start SaveKin with locally entered PayPal sandbox credentials.')
    parser.add_argument('--restart-local',action='store_true',help='Replace only the verified local SaveKin backend, after authentication succeeds.')
    parser.add_argument('--check-only',action='store_true',help='Check credentials without restarting or starting a server.')
    parser.add_argument('--with-ai',action='store_true',help='Also prompt locally for the optional AI key and model; neither is saved.')
    parser.add_argument('--with-elastic',action='store_true',help='Prompt for Elastic Cloud helper connection details and validate them before restarting.')
    parser.add_argument('--local-mail',action='store_true',help='Save verification/recovery emails as private local development previews instead of sending email.')
    options=parser.parse_args(argv)
    if options.with_ai and options.with_elastic:
        parser.error('Choose --with-ai or --with-elastic, not both.')
    environment=None
    try:
        occupied=running()
        if occupied and not (options.restart_local or options.check_only):
            print('SaveKin is running. Use --restart-local or --check-only.'); return 1
        print('SaveKin sandbox setup. Credentials are not saved to disk. No script-policy change is needed.')
        client=input('Sandbox app client ID: ').strip()
        recipient=input('Sandbox Business email (the test treasurer): ').strip().lower()
        webhook=input('Webhook ID (press Enter to skip for now): ').strip()
        if not client or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',recipient):
            print('A client ID and valid sandbox Business email are required.'); return 1
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            secret=getpass.getpass('Sandbox app secret (hidden): ')
        if not secret: print('A sandbox secret is required.'); return 1
        environment={**os.environ,'PAYMENT_MODE':'sandbox','PAYPAL_CLIENT_ID':client,
            'PAYPAL_CLIENT_SECRET':secret,'PAYPAL_TREASURER_EMAIL':recipient,'PAYPAL_WEBHOOK_ID':webhook}
        if options.local_mail:
            environment['SAVEKIN_MAIL_MODE']='local'
            print('Development email previews enabled. No verification or recovery email will be sent; previews are saved beside the database in mail-preview/.')
        if validate_credentials(environment):
            print('Existing server left unchanged.'); return 1
        if options.check_only: return 0
        if options.with_ai:
            with warnings.catch_warnings():
                warnings.simplefilter('error',getpass.GetPassWarning)
                ai_key=getpass.getpass('OpenAI API key (hidden; not saved): ').strip()
            ai_model=input('OpenAI model ID available to your account: ').strip()
            if not ai_key or not ai_model:
                print('AI key and model are both required with --with-ai. Existing server left unchanged.'); return 1
            environment.update(OPENAI_API_KEY=ai_key,OPENAI_MODEL=ai_model)
            environment['AI_PROVIDER']='openai'
        if options.with_elastic:
            environment['AI_PROVIDER']='elastic'
            environment['ELASTIC_KIBANA_URL']=input('Elastic Kibana HTTPS URL: ').strip()
            environment['ELASTIC_AGENT_ID']=input('Elastic agent ID [savekin-helper]: ').strip() or 'savekin-helper'
            with warnings.catch_warnings():
                warnings.simplefilter('error',getpass.GetPassWarning)
                environment['ELASTIC_API_KEY']=getpass.getpass('Elastic read-only client API key (hidden): ').strip()
            try:
                from elastic_setup import configure
                configure(environment)
            except Exception:
                print('Elastic connection check failed. Verify Kibana URL, agent ID and read-only key. Existing server left unchanged.'); return 1
            print('Elastic agent access: passed. A real AI reply still needs testing in the chat.')
        if running():
            if not options.restart_local:
                print('A server started during setup. Retry with --restart-local.'); return 1
            stop_verified_server()
        return subprocess.call([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=environment)
    except getpass.GetPassWarning:
        print('A terminal that supports hidden password input is required. Use the VS Code terminal.'); return 1
    except (EOFError,KeyboardInterrupt):
        print('\nSetup cancelled.'); return 1
    except (OSError,RuntimeError,subprocess.SubprocessError):
        print('Setup could not finish safely. Stop the local backend manually, then retry.'); return 1
    finally:
        if environment is not None:
            environment.pop('PAYPAL_CLIENT_SECRET',None)
            environment.pop('OPENAI_API_KEY',None)
            environment.pop('ELASTIC_API_KEY',None)

if __name__=='__main__': raise SystemExit(main())
