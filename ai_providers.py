"""Server-side AI adapters. Provider choice never comes from a chat message."""
import json
import os
import re
import urllib.request
import urllib.error
from urllib.parse import urlparse

def provider(): return os.environ.get('AI_PROVIDER','openai').strip().lower()

def ready():
    if provider()=='elastic':
        return all(os.environ.get(k,'').strip() for k in ('ELASTIC_KIBANA_URL','ELASTIC_API_KEY','ELASTIC_AGENT_ID'))
    return provider()=='openai' and bool(os.environ.get('OPENAI_API_KEY') and os.environ.get('OPENAI_MODEL'))

def base_url():
    value=os.environ.get('ELASTIC_KIBANA_URL','').strip().rstrip('/')
    parsed=urlparse(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Enter the HTTPS Kibana URL from your Elastic Cloud project, without credentials or query parameters.')
    if not any(parsed.hostname.endswith(suffix) for suffix in ('.elastic.cloud','.elastic-cloud.com','.cloud.es.io','.found.io')):
        raise ValueError('Use the Kibana endpoint of your Elastic Cloud project.')
    if parsed.path and not re.fullmatch(r'/s/[a-zA-Z0-9_-]+',parsed.path):
        raise ValueError('Use the Kibana base URL, optionally followed by /s/your-space.')
    return value

def agent_id():
    value=os.environ.get('ELASTIC_AGENT_ID','').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value): raise ValueError('Enter a valid Elastic agent ID.')
    return value

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl): return None

def elastic_request(method,path,payload=None,key=None):
    secret=key or os.environ.get('ELASTIC_API_KEY','').strip()
    if not secret: raise ValueError('An Elastic API key is required.')
    request=urllib.request.Request(base_url()+path,data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization':'ApiKey '+secret,'kbn-xsrf':'true','Content-Type':'application/json'},method=method)
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=60) as response:
        return json.load(response)

def generate(instructions,messages):
    if provider()=='elastic':
        result=elastic_request('POST','/api/agent_builder/converse',{
            'agent_id':agent_id(),
            # No provider conversation ID is reused across local users or chats.
            'input':json.dumps({'conversation':[{'role':m['role'],'content':m['content'][:4000]} for m in messages]}),
            'configuration_overrides':{'instructions':instructions,
                'enable_elastic_capabilities':False,'tools':[],'skill_ids':[]}})
        answer=result.get('response',{}).get('message','')
        if not isinstance(answer,str): raise ValueError('Elastic returned no text reply.')
        return answer
    if provider()!='openai': raise ValueError('Choose AI_PROVIDER=openai or elastic.')
    payload={'model':os.environ['OPENAI_MODEL'],'store':False,'max_output_tokens':1400,
        'instructions':instructions,'input':messages}
    request=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'],'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=40) as response: result=json.load(response)
    return '\n'.join(part['text'] for item in result.get('output',[]) if item.get('type')=='message'
        for part in item.get('content',[]) if part.get('type')=='output_text')
