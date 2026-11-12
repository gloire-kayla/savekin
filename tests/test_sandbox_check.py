import contextlib
import io
import os
import unittest
import urllib.error
from unittest.mock import patch
import sandbox_check


class SandboxCheckTests(unittest.TestCase):
    def run_check(self,response=None,error=None,missing=False):
        output=io.StringIO()
        env={'PAYPAL_CLIENT_ID':'sensitive-client','PAYPAL_CLIENT_SECRET':'sensitive-secret',
             'PAYPAL_TREASURER_EMAIL':'test@example.com','PAYPAL_WEBHOOK_ID':''}
        if missing: env['PAYPAL_CLIENT_SECRET']=''
        with patch.dict(os.environ,env),patch.object(sandbox_check.server,'paypal',return_value=response,side_effect=error) as provider,contextlib.redirect_stdout(output):
            status=sandbox_check.check()
        text=output.getvalue()
        self.assertNotIn('sensitive-client',text); self.assertNotIn('sensitive-secret',text)
        self.assertNotIn('private-access-token',text)
        return status,text,provider

    def test_success_checks_authentication_without_a_payment(self):
        status,text,provider=self.run_check({'access_token':'private-access-token'})
        self.assertEqual(status,0); self.assertIn('No payment was created',text)
        provider.assert_called_once_with('/v1/oauth2/token')

    def test_missing_secret_never_calls_provider(self):
        status,text,provider=self.run_check(missing=True)
        self.assertEqual(status,1); provider.assert_not_called()

    def test_network_error_does_not_print_sensitive_error_details(self):
        status,text,_=self.run_check(error=urllib.error.URLError('sensitive-secret private-access-token'))
        self.assertEqual(status,1); self.assertIn('could not complete',text)

    def test_invalid_provider_response_fails(self):
        status,_,_=self.run_check({'error':'invalid_client'})
        self.assertEqual(status,1)

    def test_authentication_error_is_redacted(self):
        error=urllib.error.HTTPError('https://api-m.sandbox.paypal.com/v1/oauth2/token',401,'sensitive-secret',{},io.BytesIO(b'private-access-token'))
        status,text,_=self.run_check(error=error)
        self.assertEqual(status,1); self.assertIn('HTTP 401',text)
