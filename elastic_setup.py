"""Local Elastic setup/check; never saves credentials or accesses PayPal."""
import getpass
import os
import warnings
import urllib.error
import ai_providers as ai

def hidden(label):
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        return getpass.getpass(label).strip()

def setup_agent(setup_key):
    from assistant_chat import system_instructions
    agent=ai.agent_id()
    try:
        existing=ai.elastic_request('GET','/api/agent_builder/agents/'+agent,key=setup_key)
        if existing.get('id')!=agent: raise ValueError('Unexpected agent returned.')
        if 'savekin-helper' not in existing.get('labels',[]):
            raise ValueError('That agent ID belongs to another agent. Choose a new SaveKin agent ID.')
        return
    except urllib.error.HTTPError as exc:
        code=exc.code; exc.close()
        if code!=404: raise
    ai.elastic_request('POST','/api/agent_builder/agents',{
        'id':agent,'name':'SaveKin helper','description':'SaveKin onboarding and savings-goal planning; no financial actions.',
        'labels':['savekin-helper'],'configuration':{'instructions':system_instructions(),
            'enable_elastic_capabilities':False,'tools':[]}},key=setup_key)

def check():
    result=ai.elastic_request('GET','/api/agent_builder/agents/'+ai.agent_id())
    if result.get('id')!=ai.agent_id(): raise ValueError('Elastic returned a different agent.')
    config=result.get('configuration',{})
    if config.get('enable_elastic_capabilities') or any(t.get('tool_ids') for t in config.get('tools',[])) or any(config.get(k) for k in ('workflow_ids','post_execution_workflow_ids','plugin_ids','subagent_ids','skill_ids')):
        raise ValueError('Use the dedicated SaveKin agent with optional Elastic capabilities and custom tools disabled.')

def configure(environment):
    """Read-only connection check using only the supplied child environment."""
    keys=('AI_PROVIDER','ELASTIC_KIBANA_URL','ELASTIC_API_KEY','ELASTIC_AGENT_ID')
    previous={k:os.environ.get(k) for k in keys}
    try:
        for key in keys: os.environ[key]=environment.get(key,'')
        check()
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value

def main():
    keys=('AI_PROVIDER','ELASTIC_KIBANA_URL','ELASTIC_API_KEY','ELASTIC_AGENT_ID')
    previous={k:os.environ.get(k) for k in keys}
    try:
        print('Create/check the SaveKin agent in your Elastic Cloud project. Keys are not saved.')
        os.environ['ELASTIC_KIBANA_URL']=input('Elastic Kibana HTTPS URL: ').strip()
        os.environ['ELASTIC_AGENT_ID']=input('Agent ID [savekin-helper]: ').strip() or 'savekin-helper'
        ai.base_url(); ai.agent_id()
        setup_key=hidden('Temporary agent-management API key (hidden): ')
        setup_agent(setup_key)
        setup_key=''
        print('SaveKin agent is available. Use a separate read-only client key when starting SaveKin.')
        return 0
    except (KeyboardInterrupt,EOFError): print('Setup cancelled.'); return 1
    except urllib.error.HTTPError as exc:
        print(f'Elastic setup returned HTTP {exc.code}. Check Kibana URL, trial availability and management privileges.'); exc.close(); return 1
    except ValueError as exc: print(str(exc)); return 1
    except Exception: print('Elastic setup could not connect. No key was printed.'); return 1
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value

if __name__=='__main__': raise SystemExit(main())
