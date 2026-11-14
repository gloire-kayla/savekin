import importlib
import json
import os
import tempfile
import unittest
import http.client
import threading
import io
from datetime import date
from unittest.mock import patch

import savekin as sk

class SaveKinTests(unittest.TestCase):
    def setUp(self):
        self.credentials=patch.dict(os.environ,{'PAYPAL_CLIENT_ID':'test-client','PAYPAL_CLIENT_SECRET':'test-secret'})
        self.credentials.start()
        self.temp=tempfile.TemporaryDirectory()
        self.old_db=sk.core.DB
        sk.core.DB=sk.core.Path(self.temp.name)/'savekin.sqlite3'
        with sk.core.connect() as db: db.executescript(sk.SCHEMA)
        self.old_mode=sk.core.MODE; sk.core.MODE='demo'
        self.a=self.register('Alice'); self.b=self.register('Bob'); self.c=self.register('Cara')

    def tearDown(self):
        sk.core.DB=self.old_db; sk.core.MODE=self.old_mode; self.temp.cleanup(); self.credentials.stop()

    def register(self,name):
        return sk.dispatch('POST','/api/auth/register',{'name':name,'email':name.lower()+'@example.com','password':'unique-test-password-123'})['token']

    def call(self,path,body=None,token=None):
        return sk.dispatch('POST',path,body or {},token or self.a)

    def group(self,**changes):
        payload={'name':'Family fund','currency':'USD','sharePrice':'1','shares':'2','goal':'1000','end':date.today().isoformat(),
          'ending':'repeat','months':'12','fine':'0.01','exitPenalty':'1','joining':'catch_up','surplus':'distribute'}
        payload.update(changes)
        gid=self.call('/api/groups',payload)['id']
        return gid

    def snap(self,gid,token=None):
        return next(g for g in sk.dispatch('GET','/api/state',{},token or self.a)['groups'] if g['id']==gid)

    def join(self,gid,token,shares='1'):
        self.call('/api/join',{'invite':self.snap(gid)['invite'],'shares':shares,'acceptRules':True},token)

    def elect(self,gid):
        self.join(gid,self.b)
        bob=sk.dispatch('GET','/api/state',{},self.b)['user']['id']
        pid=self.call('/api/proposals',{'groupId':gid,'kind':'treasurer','userId':bob})['proposalId']
        self.call('/api/vote',{'groupId':gid,'proposalId':pid,'approve':True})
        self.assertIsNone(self.snap(gid)['treasurer'])
        self.call('/api/vote',{'groupId':gid,'proposalId':pid,'approve':True},self.b)
        self.assertEqual(self.snap(gid)['treasurer'],bob)
        self.call('/api/treasury/account',{'groupId':gid,'email':'bob@example.com','confirm':True},self.b)

    def test_auth_isolation_and_method_checks(self):
        gid=self.group()
        self.assertEqual(sk.dispatch('GET','/api/state',{},self.b)['groups'],[])
        with self.assertRaises(sk.Problem): self.call('/api/shares',{'groupId':gid,'shares':'4','when':'now'},self.b)
        with self.assertRaises(sk.Problem): sk.dispatch('GET','/api/auth/logout',{},self.a)
        self.call('/api/auth/logout',token=self.a)
        with self.assertRaises(sk.Problem): sk.dispatch('GET','/api/state',{},self.a)

    def test_waiting_members_and_catchup(self):
        gid=self.group(joining='next_cycle')
        self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        self.join(gid,self.b)
        bob=next(m for m in self.snap(gid)['members'] if m['name']=='Bob')
        self.assertEqual(bob['status'],'waiting')
        with self.assertRaises(sk.Problem): self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)
        self.call('/api/shares',{'groupId':gid,'shares':'4','when':'now'})
        self.assertEqual(next(m for m in self.snap(gid)['members'] if m['name']=='Alice')['arrears'],200)
        with self.assertRaises(sk.Problem): self.call('/api/shares',{'groupId':gid,'shares':'1','when':'now'})

    def test_share_increase_catches_all_elapsed_months(self):
        gid=self.group()
        today=date.today(); month=today.month-2; year=today.year
        if month<1: month+=12; year-=1
        with sk.core.connect() as db: db.execute('UPDATE sk_cycles SET start=? WHERE group_id=?',(date(year,month,1).isoformat(),gid))
        self.call('/api/contribute',{'groupId':gid,'amount':'6'})
        self.call('/api/shares',{'groupId':gid,'shares':'3','when':'now'})
        member=self.snap(gid)['members'][0]
        self.assertEqual(member['due'],900); self.assertEqual(member['arrears'],300)

    def test_role_rules_and_duplicate_votes(self):
        gid=self.group(); self.elect(gid)
        with self.assertRaises(sk.Problem): self.call('/api/proposals',{'groupId':gid,'kind':'treasurer','userId':self.snap(gid)['president']})
        rules=self.snap(gid)['rules']
        proposed={**rules,'sharePrice':'1','goal':'1000','fine':'2','exitPenalty':'1','months':'12'}
        pid=self.call('/api/proposals',{'groupId':gid,'kind':'rules','rules':proposed})['proposalId']
        self.call('/api/vote',{'groupId':gid,'proposalId':pid,'approve':True})
        self.assertEqual(self.snap(gid)['rules']['fine'],1)
        self.call('/api/vote',{'groupId':gid,'proposalId':pid,'approve':True},self.b)
        self.assertEqual(self.snap(gid)['rules']['fine'],200)

    def test_rounding_dual_approval_and_repeat(self):
        gid=self.group(); self.elect(gid)
        self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)
        bob=next(m for m in self.snap(gid)['members'] if m['name']=='Bob')
        self.call('/api/fine',{'groupId':gid,'memberId':bob['id']})
        snap=self.snap(gid)
        self.assertEqual(sum(a['amount'] for a in snap['allocations']),301)
        self.assertTrue(snap['canSettle'])
        pid=self.call('/api/proposals',{'groupId':gid,'kind':'settlement'})['proposalId']
        with self.assertRaises(sk.Problem): self.call('/api/contribute',{'groupId':gid,'amount':'1'})
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        self.assertEqual(self.snap(gid)['cycle']['status'],'review')
        with self.assertRaises(sk.Problem): self.call('/api/complete',{'groupId':gid},self.b)
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True},self.b)
        self.call('/api/complete',{'groupId':gid},self.b)
        with self.assertRaises(sk.Problem): self.call('/api/complete',{'groupId':gid},self.b)
        self.call('/api/next-cycle',{'groupId':gid})
        snap=self.snap(gid); self.assertEqual(snap['cycle']['number'],2); self.assertEqual(snap['gross'],0)

    def funded_settlement(self):
        gid=self.group(); self.elect(gid)
        self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)
        pid=self.call('/api/proposals',{'groupId':gid,'kind':'settlement'})['proposalId']
        return gid,pid

    def test_settlement_requires_explicit_consent_from_each_officer(self):
        gid,pid=self.funded_settlement()
        for value in (None,'true',1):
            with self.subTest(value=value),self.assertRaises(sk.Problem):
                self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':value})
        self.assertEqual(self.snap(gid)['proposals'][0]['approvals'],[])
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        self.assertEqual(self.snap(gid)['cycle']['status'],'review')
        with self.assertRaises(sk.core.sqlite3.IntegrityError):
            self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        with self.assertRaises(sk.Problem):
            self.call('/api/complete',{'groupId':gid},self.b)
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True},self.b)
        self.assertEqual(self.snap(gid)['cycle']['status'],'approved')
        with self.assertRaises(sk.Problem): self.call('/api/complete',{'groupId':gid})

    def test_rejected_settlement_reopens_cycle_without_distribution(self):
        gid,pid=self.funded_settlement()
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':False},self.b)
        snap=self.snap(gid)
        self.assertEqual(snap['cycle']['status'],'open')
        self.assertEqual(snap['pool'],300)
        self.assertEqual(snap['proposals'][0]['status'],'rejected')
        with self.assertRaises(sk.Problem): self.call('/api/complete',{'groupId':gid},self.b)

    def test_surplus_uses_shares_while_returning_each_members_actual_principal(self):
        gid=self.group(); self.elect(gid)
        self.call('/api/contribute',{'groupId':gid,'amount':'5'})
        self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)
        bob=next(m for m in self.snap(gid)['members'] if m['name']=='Bob')
        self.call('/api/fine',{'groupId':gid,'memberId':bob['id']})
        allocations={a['name']:a for a in self.snap(gid)['allocations']}
        self.assertEqual(allocations['Alice']['amount'],501)
        self.assertEqual(allocations['Bob']['amount'],100)
        self.assertEqual(sum(a['amount'] for a in allocations.values()),601)

    def test_exit_penalty_preserves_pool_and_blocks_changes(self):
        gid=self.group(); self.elect(gid); self.join(gid,self.c)
        self.call('/api/contribute',{'groupId':gid,'amount':'5'},self.c)
        pid=self.call('/api/proposals',{'groupId':gid,'kind':'exit'},self.c)['proposalId']
        with self.assertRaises(sk.Problem): self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.c)
        self.assertFalse(self.snap(gid)['canSettle'])
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True},self.b)
        self.call('/api/complete',{'groupId':gid,'kind':'exit','proposalId':pid},self.b)
        snap=self.snap(gid); self.assertEqual(snap['pool'],100)
        self.assertEqual(next(m for m in snap['members'] if m['name']=='Cara')['status'],'left')

    def test_goal_reached_still_allows_arrears(self):
        gid=self.group(ending='goal',goal='2'); self.elect(gid)
        self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        self.assertEqual(self.snap(gid)['cycle']['status'],'goal_reached')
        self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)
        self.assertTrue(self.snap(gid)['canSettle'])
        with self.assertRaises(sk.Problem): self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)

    def test_sandbox_capture_is_scoped_net_of_fees_and_idempotent(self):
        gid=self.group(); self.elect(gid)
        alice=next(m for m in self.snap(gid)['members'] if m['name']=='Alice')
        with patch.object(sk.core,'MODE','sandbox'),patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'bob@example.com'}),patch.object(sk.core,'paypal') as paypal:
            paypal.side_effect=[{'access_token':'test'},{'id':'SCOPED-ORDER'}]
            order=self.call('/api/paypal/orders',{'groupId':gid,'amount':'2.50'})
            with self.assertRaises(sk.Problem):
                self.call('/api/paypal/capture',{'groupId':gid,'orderId':order['id']},self.b)
            paypal.side_effect=[{'access_token':'test'},{'status':'COMPLETED','purchase_units':[{
                'payee':{'email_address':'bob@example.com'},'payments':{'captures':[{
                'id':'SCOPED-CAPTURE','status':'COMPLETED','amount':{'currency_code':'USD','value':'2.50'},
                'seller_receivable_breakdown':{'paypal_fee':{'currency_code':'USD','value':'0.10'}}}]}}]}]
            self.call('/api/paypal/capture',{'groupId':gid,'orderId':order['id']})
            self.call('/api/paypal/capture',{'groupId':gid,'orderId':order['id']})
        snap=self.snap(gid)
        self.assertEqual(snap['gross'],240); self.assertEqual(snap['pool'],240)
        self.assertEqual(len([e for e in snap['ledger'] if e['kind']=='contribution']),1)
        self.assertEqual(sum(e['amount'] for e in snap['ledger'] if e['kind']=='provider_fee'),10)

    def test_rwf_surplus_allocation_uses_whole_francs(self):
        gid=self.group(currency='RWF',sharePrice='100',fine='1',exitPenalty='100',goal='10000')
        self.elect(gid)
        self.call('/api/contribute',{'groupId':gid,'amount':'200'})
        self.call('/api/contribute',{'groupId':gid,'amount':'100'},self.b)
        bob=next(m for m in self.snap(gid)['members'] if m['name']=='Bob')
        self.call('/api/fine',{'groupId':gid,'memberId':bob['id']})
        snap=self.snap(gid)
        self.assertEqual(sum(a['amount'] for a in snap['allocations']),30100)
        self.assertTrue(all(a['amount']%100==0 for a in snap['allocations']))

    def test_carry_forward_excludes_surplus_from_distribution(self):
        gid=self.group(surplus='carry'); self.elect(gid)
        self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)
        bob=next(m for m in self.snap(gid)['members'] if m['name']=='Bob')
        self.call('/api/fine',{'groupId':gid,'memberId':bob['id']})
        snap=self.snap(gid)
        self.assertEqual(snap['carried'],1)
        self.assertEqual(sum(a['amount'] for a in snap['allocations']),300)

    def test_http_session_cookie_and_cross_origin_protection(self):
        httpd=sk.core.ThreadingHTTPServer(('127.0.0.1',0),sk.Handler)
        thread=threading.Thread(target=httpd.serve_forever,daemon=True); thread.start()
        client=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=4)
        try:
            client.request('GET','/')
            response=client.getresponse(); self.assertEqual(response.status,200)
            page=response.read().decode()
            self.assertLess(page.index('/helper.js'),page.index('/app.js'))
            client.request('GET','/helper.js')
            response=client.getresponse(); self.assertEqual(response.status,200)
            self.assertIn('text/javascript',response.getheader('Content-Type'))
            self.assertIn('function helperPanel()',response.read().decode())
            client.request('GET','/workspace.js')
            response=client.getresponse(); self.assertEqual(response.status,200)
            self.assertIn('function profilePanel()',response.read().decode())
            client.request('GET','/api/state')
            response=client.getresponse(); self.assertEqual(response.status,401); response.read()
            credentials=json.dumps({'email':'alice@example.com','password':'unique-test-password-123'})
            client.request('POST','/api/auth/login',credentials,{'Host':'127.0.0.1:8000','Content-Type':'application/json'})
            response=client.getresponse(); self.assertEqual(response.status,200)
            cookie=response.getheader('Set-Cookie'); self.assertIn('HttpOnly',cookie); self.assertIn('SameSite=Strict',cookie); response.read()
            client.request('GET','/api/state',headers={'Cookie':cookie.split(';')[0]})
            response=client.getresponse(); self.assertEqual(response.status,200)
            self.assertEqual(json.loads(response.read())['user']['name'],'Alice')
            client.request('POST','/api/auth/logout','{}',{'Host':'127.0.0.1:8000','Cookie':cookie.split(';')[0],'Origin':'https://untrusted.example'})
            response=client.getresponse(); self.assertEqual(response.status,403); response.read()
        finally:
            client.close(); httpd.shutdown(); httpd.server_close(); thread.join()

    def test_render_health_check_and_secure_session_cookie(self):
        httpd=sk.core.ThreadingHTTPServer(('127.0.0.1',0),sk.Handler)
        thread=threading.Thread(target=httpd.serve_forever,daemon=True); thread.start()
        client=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=4)
        try:
            client.request('GET','/healthz')
            response=client.getresponse()
            self.assertEqual(response.status,200)
            self.assertEqual(json.loads(response.read()),{'ok':True})
            credentials=json.dumps({'email':'alice@example.com','password':'unique-test-password-123'})
            with patch.dict(os.environ,{
                'RENDER':'true',
                'RENDER_EXTERNAL_HOSTNAME':'savekin.onrender.com',
                'RENDER_EXTERNAL_URL':'https://savekin.onrender.com',
            }):
                client.request('POST','/api/auth/login',credentials,{
                    'Host':'savekin.onrender.com',
                    'Origin':'https://savekin.onrender.com',
                    'Content-Type':'application/json',
                })
                response=client.getresponse()
                self.assertEqual(response.status,200)
                self.assertIn('Secure',response.getheader('Set-Cookie'))
                response.read()
        finally:
            client.close(); httpd.shutdown(); httpd.server_close(); thread.join()

    def test_assistant_requires_consent_and_uses_limited_context(self):
        gid=self.group()
        with self.assertRaises(sk.Problem): self.call('/api/assistant',{'groupId':gid,'question':'What is due?'})
        fake={'output':[{'type':'message','content':[{'type':'output_text','text':'Your monthly contribution is USD 2.'}]}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-key','OPENAI_MODEL':'test-model'}),patch.object(sk.core.urllib.request,'urlopen') as http:
            http.return_value=io.BytesIO(json.dumps(fake).encode())
            result=self.call('/api/assistant',{'groupId':gid,'question':'What is due?','consent':True})
            payload=json.loads(http.call_args.args[0].data)
            self.assertFalse(payload['store'])
            self.assertNotIn('alice@example.com',json.dumps(payload['input']))
            self.assertNotIn(self.snap(gid)['invite'],json.dumps(payload['input']))
            self.assertIn('USD 2',result['answer'])
            self.assertEqual(self.snap(gid)['ledger'],[])

    def test_assistant_does_not_fake_a_response_without_configuration(self):
        gid=self.group()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','OPENAI_MODEL':''}):
            with self.assertRaises(sk.Problem) as error:
                self.call('/api/assistant',{'groupId':gid,'question':'What is due?','consent':True})
            self.assertEqual(error.exception.status,503)

if __name__=='__main__': unittest.main()
