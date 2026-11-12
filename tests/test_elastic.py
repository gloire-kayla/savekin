import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch
import ai_providers as ai
import elastic_setup

ENV={'AI_PROVIDER':'elastic','ELASTIC_KIBANA_URL':'https://savekin.kb.us-east-1.aws.elastic.cloud',
    'ELASTIC_API_KEY':'private-runtime-key','ELASTIC_AGENT_ID':'savekin-helper'}

class ElasticTests(unittest.TestCase):
    def test_invalid_or_non_cloud_urls_are_rejected_before_transmission(self):
        for url in ('http://localhost:8000','https://evil.example','https://name:key@host.elastic.cloud','https://a.elastic.cloud/path?key=x'):
            with patch.dict(os.environ,{**ENV,'ELASTIC_KIBANA_URL':url}),patch.object(ai.urllib.request,'build_opener') as opener:
                with self.assertRaises(ValueError): ai.elastic_request('GET','/api/agent_builder/agents/test')
                opener.assert_not_called()

    def test_api_key_is_in_header_not_url_or_body_and_redirects_are_blocked(self):
        with patch.dict(os.environ,ENV),patch.object(ai.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(b'{"id":"savekin-helper"}')
            ai.elastic_request('GET','/api/agent_builder/agents/savekin-helper')
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'),'ApiKey private-runtime-key')
            self.assertNotIn('private-runtime-key',request.full_url)
            self.assertIsNone(ai.NoRedirect().redirect_request(request,None,302,'redirect',{},'https://evil.example'))

    def test_elastic_uses_local_history_without_reusing_remote_conversation(self):
        messages=[{'role':'user','content':'Help choose a goal'},{'role':'assistant','content':'What timeframe?'},{'role':'user','content':'One year'}]
        with patch.dict(os.environ,ENV),patch.object(ai,'elastic_request',return_value={'conversation_id':'remote-private','response':{'message':'Here is a draft plan.'}}) as request:
            self.assertEqual(ai.generate('SaveKin trusted instructions',messages),'Here is a draft plan.')
            data=request.call_args.args[2]
            self.assertNotIn('conversation_id',data)
            self.assertEqual(json.loads(data['input'])['conversation'],messages)
            self.assertEqual(data['configuration_overrides']['tools'],[])
            self.assertFalse(data['configuration_overrides']['enable_elastic_capabilities'])
            self.assertNotIn('OPENAI_API_KEY',json.dumps(data))

    def test_missing_elastic_configuration_does_not_fall_back_to_openai(self):
        with patch.dict(os.environ,{'AI_PROVIDER':'elastic','OPENAI_API_KEY':'unrelated','OPENAI_MODEL':'unrelated'},clear=True):
            self.assertFalse(ai.ready())

    def test_setup_creates_dedicated_agent_without_optional_tools(self):
        missing=urllib.error.HTTPError('https://savekin.elastic.cloud',404,'Missing',{},io.BytesIO(b'{}'))
        with patch.dict(os.environ,ENV),patch.object(ai,'elastic_request',side_effect=[missing,{'id':'savekin-helper'}]) as request:
            elastic_setup.setup_agent('temporary-management-key')
            data=request.call_args.args[2]
            self.assertEqual(data['labels'],['savekin-helper'])
            self.assertEqual(data['configuration']['tools'],[])
            self.assertIn('SaveKin product guide',data['configuration']['instructions'])

    def test_setup_does_not_overwrite_unrelated_agent(self):
        with patch.dict(os.environ,ENV),patch.object(ai,'elastic_request',return_value={'id':'savekin-helper','labels':['unrelated']}) as request:
            with self.assertRaises(ValueError): elastic_setup.setup_agent('temporary-key')
            self.assertEqual(request.call_count,1)

    def test_connection_check_restores_environment_and_makes_no_model_call(self):
        with patch.dict(os.environ,{'ELASTIC_API_KEY':'original'}),patch.object(ai,'elastic_request',return_value={'id':'savekin-helper','configuration':{'tools':[]}}) as request:
            elastic_setup.configure(ENV)
            self.assertEqual(os.environ['ELASTIC_API_KEY'],'original')
            self.assertEqual(request.call_args.args[0],'GET')
