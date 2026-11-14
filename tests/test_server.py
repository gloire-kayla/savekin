"""Critical money and API checks; all records use a temporary database."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

tmp = tempfile.TemporaryDirectory()
os.environ['GATHERSAVE_DATA_DIR'] = tmp.name
os.environ['PAYMENT_MODE'] = 'demo'
spec = importlib.util.spec_from_file_location('gathersave_server', Path(__file__).resolve().parents[1] / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class MoneyTests(unittest.TestCase):
    def test_exact_cents(self):
        self.assertEqual(server.amount('19.99'), 1999)
        self.assertEqual(server.amount('0.01'), 1)

    def test_invalid_amounts(self):
        for value in ['0', '-1', 'NaN', 'Infinity', '1.005', '1000001', 'oops']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.amount(value)

class DeploymentConfigTests(unittest.TestCase):
    def test_render_host_and_https_origin_are_added_without_widening_local_defaults(self):
        with patch.dict(os.environ, {
            'RENDER_EXTERNAL_HOSTNAME': 'savekin.onrender.com',
            'RENDER_EXTERNAL_URL': 'https://savekin.onrender.com',
        }):
            self.assertIn('savekin.onrender.com', server.allowed_hosts())
            self.assertIn('https://savekin.onrender.com', server.allowed_origins())
            self.assertNotIn('https://untrusted.example', server.allowed_origins())

    def test_non_https_render_url_is_not_allowed_as_an_origin(self):
        with patch.dict(os.environ, {
            'RENDER_EXTERNAL_HOSTNAME': 'savekin.onrender.com',
            'RENDER_EXTERNAL_URL': 'http://savekin.onrender.com',
        }):
            self.assertNotIn('http://savekin.onrender.com', server.allowed_origins())

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, data=None, origin=None):
        headers={'Host':'127.0.0.1:8000', 'Content-Type':'application/json'}
        if origin: headers['Origin']=origin
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,
            data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(req) as r: return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            with e: return e.code,json.load(e)

    def group(self):
        status,result=self.request('/api/groups',{'name':'Test circle','treasurer':'Alex','goal':'1000','contribution':'25','deadline':'2027-01-01'})
        self.assertEqual(status,201,result)
        return result['id']

    def test_contribution_persists_and_is_scoped(self):
        gid=self.group()
        self.assertEqual(self.request('/api/members',{'groupId':gid,'name':'Sam','email':'sam@example.com'})[0],201)
        current=self.request('/api/state')[1]
        member=next(m for m in current['members'] if m['group_id']==gid)
        self.assertEqual(self.request('/api/payments/demo',{'groupId':gid,'memberId':member['id'],'amount':'19.99'})[0],201)
        records=self.request('/api/state')[1]['payments']
        payment=next(p for p in records if p['group_id']==gid)
        self.assertEqual(payment['amount'],1999)
        self.assertEqual(payment['kind'],'demo')
        other=self.group()
        self.assertEqual(self.request('/api/payments/demo',{'groupId':other,'memberId':member['id'],'amount':'20'})[0],400)

    def test_duplicate_member_rejected(self):
        gid=self.group()
        body={'groupId':gid,'name':'Sam','email':'sam@example.com'}
        self.assertEqual(self.request('/api/members',body)[0],201)
        self.assertEqual(self.request('/api/members',body)[0],409)

    def test_cross_origin_write_rejected(self):
        self.assertEqual(self.request('/api/groups',{},'https://untrusted.example')[0],403)

    def test_sandbox_capture_verification_and_idempotency(self):
        gid=self.group()
        self.request('/api/members',{'groupId':gid,'name':'Jamie','email':'jamie@example.com'})
        member=next(m for m in self.request('/api/state')[1]['members'] if m['group_id']==gid)
        body={'groupId':gid,'memberId':member['id'],'amount':'25'}
        capture={'status':'COMPLETED','purchase_units':[{'payments':{'captures':[{
            'id':'CAPTURE-TEST','status':'COMPLETED','amount':{'currency_code':'USD','value':'25.00'}}]}}]}
        with patch.object(server,'MODE','sandbox'), patch.object(server,'paypal') as paypal:
            paypal.side_effect=[{'access_token':'token'},{'id':'ORDER-TEST'}]
            self.assertEqual(self.request('/api/paypal/orders',body)[0],200)
            paypal.side_effect=[{'access_token':'token'},capture]
            capture_body={**body,'orderId':'ORDER-TEST'}
            self.assertEqual(self.request('/api/paypal/capture',capture_body)[0],200)
            self.assertEqual(self.request('/api/paypal/capture',capture_body)[0],200)
            self.assertEqual(paypal.call_count,4)
        records=[p for p in self.request('/api/state')[1]['payments'] if p['group_id']==gid]
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['amount'],2500)

    def test_unconfirmed_capture_never_credits_ledger(self):
        gid=self.group()
        self.request('/api/members',{'groupId':gid,'name':'Pat','email':'pat@example.com'})
        member=next(m for m in self.request('/api/state')[1]['members'] if m['group_id']==gid)
        with server.connect() as db:
            db.execute('INSERT INTO orders VALUES (?,?,?,?,0)',('ORDER-PENDING',gid,member['id'],2500))
        with patch.object(server,'MODE','sandbox'),patch.object(server,'paypal') as paypal:
            paypal.side_effect=[{'access_token':'token'},{'status':'COMPLETED','purchase_units':[{'payments':{'captures':[{
                'id':'PENDING','status':'PENDING','amount':{'currency_code':'USD','value':'25.00'}}]}}]}]
            self.assertEqual(self.request('/api/paypal/capture',{'groupId':gid,'memberId':member['id'],'orderId':'ORDER-PENDING'})[0],400)
        self.assertFalse(any(p['group_id']==gid for p in self.request('/api/state')[1]['payments']))

if __name__ == '__main__':
    unittest.main()
