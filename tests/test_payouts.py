import copy
import io
import json
import os
import unittest
from unittest.mock import patch
import savekin as sk
import test_savekin as fixtures


class SandboxPayoutTests(unittest.TestCase):
    setUp=fixtures.SaveKinTests.setUp
    tearDown=fixtures.SaveKinTests.tearDown
    register=fixtures.SaveKinTests.register
    call=fixtures.SaveKinTests.call
    group=fixtures.SaveKinTests.group
    snap=fixtures.SaveKinTests.snap
    join=fixtures.SaveKinTests.join
    elect=fixtures.SaveKinTests.elect

    def prepare(self):
        self.gid=self.group(); self.elect(self.gid)
        self.call('/api/contribute',{'groupId':self.gid,'amount':'2'})
        self.call('/api/contribute',{'groupId':self.gid,'amount':'1'},self.b)
        for token,email in ((self.a,'buyer@personal.example.com'),(self.b,'bob@example.com')):
            self.call('/api/payout-account',{'email':email,'sandboxOnly':True},token)
        sk.core.MODE='sandbox'
        pid=self.call('/api/proposals',{'groupId':self.gid,'kind':'settlement'})['proposalId']
        for token in (self.a,self.b): self.call('/api/approve',{'groupId':self.gid,'proposalId':pid,'approve':True},token)
        self.calls=[]; self.status='SUCCESS'; self.payload=None; self.fail=False; self.mismatch=False
        self.env=patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'bob@example.com'}); self.env.start(); self.addCleanup(self.env.stop)
        self.mock=patch.object(sk.core,'paypal',side_effect=self.provider); self.mock.start(); self.addCleanup(self.mock.stop)

    def provider(self,path,payload=None,token=None,request_id=None,method=None):
        self.calls.append((path,copy.deepcopy(payload),request_id))
        if path=='/v1/oauth2/token': return {'access_token':'mock'}
        if path=='/v1/notifications/verify-webhook-signature': return {'verification_status':'SUCCESS'}
        if path=='/v1/payments/payouts':
            if self.payload is not None: self.assertEqual(payload,self.payload)
            self.payload=copy.deepcopy(payload)
            if self.fail: raise TimeoutError()
            return {'batch_header':{'payout_batch_id':'BATCH1','sender_batch_header':payload['sender_batch_header']}}
        if path.startswith('/v1/payments/payouts/BATCH1?'):
            item=copy.deepcopy(self.payload['items'][0])
            if self.mismatch: item['amount']['value']='999.00'
            return {'batch_header':{'payout_batch_id':'BATCH1','sender_batch_header':self.payload['sender_batch_header']},
                'items':[{'payout_item_id':'ITEM1','transaction_status':self.status,'payout_item':item}]}
        raise AssertionError(path)

    def send(self,token=None):
        return self.call('/api/payouts/send',{'groupId':self.gid,'confirm':True},token or self.b)

    def check(self): return self.call('/api/payouts/check',{'groupId':self.gid},self.b)

    def test_frozen_distribution_and_retained_treasury_are_idempotent(self):
        self.prepare()
        self.call('/api/payout-account',{'email':'changed@personal.example.com','sandboxOnly':True})
        self.assertEqual(self.send()['status'],'complete')
        self.assertEqual(self.payload['items'][0]['receiver'],'buyer@personal.example.com')
        self.assertEqual(self.payload['items'][0]['amount']['value'],'2.00')
        self.send(); self.check()
        self.assertEqual(sum(p=='/v1/payments/payouts' for p,_,_ in self.calls),1)
        snap=self.snap(self.gid)
        self.assertEqual(snap['cycle']['status'],'distributed')
        self.assertEqual({i['status'] for i in snap['payoutItems']},{'SUCCESS','retained'})
        self.call('/api/next-cycle',{'groupId':self.gid})
        self.assertEqual(self.snap(self.gid)['cycle']['number'],2)

    def test_pending_unclaimed_and_failed_items_do_not_finish_cycle(self):
        self.prepare()
        for status in ('PENDING','UNCLAIMED','FAILED'):
            self.status=status
            self.send()
            self.assertNotEqual(self.snap(self.gid)['cycle']['status'],'distributed')
            with self.assertRaises(sk.Problem): self.call('/api/next-cycle',{'groupId':self.gid})
        self.assertEqual(sum(p=='/v1/payments/payouts' for p,_,_ in self.calls),1)
        self.status='SUCCESS'; self.check()
        self.assertEqual(self.snap(self.gid)['cycle']['status'],'distributed')

    def test_timeout_retains_request_and_reuses_same_batch(self):
        self.prepare(); self.fail=True
        with self.assertRaises(TimeoutError): self.send()
        snap=self.snap(self.gid)
        self.assertEqual(snap['payoutBatch']['status'],'unknown')
        self.assertEqual(snap['cycle']['status'],'paying')
        with self.assertRaises(sk.Problem): self.call('/api/payout-account',{'email':'new@example.com','sandboxOnly':True})
        self.fail=False; self.send()
        posts=[(p,r) for path,p,r in self.calls if path=='/v1/payments/payouts']
        self.assertEqual(posts[0],posts[1])

    def test_provider_duplicate_response_recovers_original_batch(self):
        self.prepare(); self.fail=True
        with self.assertRaises(TimeoutError): self.send()
        provider=self.provider
        def duplicate(path,*args,**kwargs):
            if path=='/v1/payments/payouts':
                body={'details':[{'issue':'DUPLICATE_BATCH_ID','links':[{'href':'https://api.sandbox.paypal.com/v1/payments/payouts/BATCH1'}]}]}
                raise sk.core.urllib.error.HTTPError('https://api-m.sandbox.paypal.com/v1/payments/payouts',400,'Bad request',{},io.BytesIO(json.dumps(body).encode()))
            return provider(path,*args,**kwargs)
        with patch.object(sk.core,'paypal',side_effect=duplicate):
            self.assertEqual(self.send()['status'],'complete')

    def test_denied_batch_without_items_is_flagged_for_review(self):
        self.prepare(); provider=self.provider
        def denied(path,*args,**kwargs):
            result=provider(path,*args,**kwargs)
            if path.startswith('/v1/payments/payouts/BATCH1?'):
                result['batch_header']['batch_status']='DENIED'; result['items']=[]
            return result
        with patch.object(sk.core,'paypal',side_effect=denied):
            self.assertEqual(self.send()['status'],'review')
        self.assertEqual(self.snap(self.gid)['cycle']['status'],'paying')

    def test_only_treasurer_can_send_and_confirm_is_required(self):
        self.prepare()
        with self.assertRaises(sk.Problem): self.send(self.a)
        with self.assertRaises(sk.Problem): self.call('/api/payouts/send',{'groupId':self.gid},self.b)
        self.assertEqual(self.calls,[])
        self.assertIsNone(self.snap(self.gid)['payoutBatch'])

    def test_unknown_batch_cannot_be_retried_under_different_app(self):
        self.prepare(); self.fail=True
        with self.assertRaises(TimeoutError): self.send()
        self.fail=False
        with patch.dict(os.environ,{'PAYPAL_CLIENT_ID':'different-app'}):
            with self.assertRaises(sk.Problem): self.send()
        self.assertEqual(sum(p=='/v1/payments/payouts' for p,_,_ in self.calls),1)

    def test_mismatched_provider_item_never_finishes_cycle(self):
        self.prepare(); self.mismatch=True
        with self.assertRaises(sk.Problem): self.send()
        self.assertEqual(self.snap(self.gid)['cycle']['status'],'paying')
        self.mismatch=False; self.check()
        self.assertEqual(self.snap(self.gid)['cycle']['status'],'distributed')

    def test_returned_payout_marks_distributed_cycle_for_review(self):
        self.prepare(); self.send(); self.status='RETURNED'; self.check()
        self.assertEqual(self.snap(self.gid)['cycle']['status'],'reconciliation_required')

    def test_signed_payout_notification_refreshes_existing_batch_once(self):
        import payments
        self.prepare(); self.status='PENDING'; self.send(); self.status='SUCCESS'
        headers={'PAYPAL-AUTH-ALGO':'SHA256withRSA','PAYPAL-CERT-URL':'https://api.paypal.com/cert.pem',
            'PAYPAL-TRANSMISSION-ID':'TEST','PAYPAL-TRANSMISSION-SIG':'mock','PAYPAL-TRANSMISSION-TIME':'2026-11-10T00:00:00Z'}
        event={'id':'PAYOUT-EVENT','event_type':'PAYMENT.PAYOUTS-ITEM.SUCCEEDED','resource':{'payout_batch_id':'BATCH1'}}
        with patch.dict(os.environ,{'PAYPAL_WEBHOOK_ID':'WEBHOOK'}):
            self.assertEqual(payments.webhook(headers,event)['status'],'processed')
            self.assertTrue(payments.webhook(headers,event)['duplicate'])
        self.assertEqual(self.snap(self.gid)['cycle']['status'],'distributed')
        self.assertEqual(sum(p=='/v1/payments/payouts' for p,_,_ in self.calls),1)

    def test_late_contribution_adjustment_blocks_new_payout_requests(self):
        import payments
        self.prepare(); self.status='PENDING'; self.send()
        snap=self.snap(self.gid)
        with sk.core.connect() as db:
            member=snap['members'][0]
            db.execute('INSERT INTO sk_orders VALUES(?,?,?,?,?,?,0)',('LATE',self.gid,snap['cycle']['id'],member['id'],member['user_id'],200))
            db.execute('INSERT INTO sk_payment_state(order_id,recipient,status,updated) VALUES(?,?,?,?)',('LATE','bob@example.com','created',sk.core.now()))
            order=sk.row(db,'SELECT * FROM sk_orders WHERE id=?',('LATE',))
            payments.invalidate(db,order,'test','Late refund during payout')
        with self.assertRaises(sk.Problem): self.send()
        self.assertEqual(self.snap(self.gid)['cycle']['status'],'reconciliation_required')

    def test_handoff_is_short_lived_and_single_use(self):
        gid=self.group(); sk.core.MODE='sandbox'
        link=self.call('/api/checkout-link',{'groupId':gid})
        result=sk.dispatch('POST','/api/auth/handoff',{'code':link['code']})
        self.assertEqual(result['groupId'],gid)
        self.assertEqual(sk.dispatch('GET','/api/state',{},result['token'])['user']['email'],'alice@example.com')
        with self.assertRaises(sk.Problem): sk.dispatch('POST','/api/auth/handoff',{'code':link['code']})
        link=self.call('/api/checkout-link',{'groupId':gid})
        with patch.object(sk.time,'time',return_value=sk.time.time()+100):
            with self.assertRaises(sk.Problem): sk.dispatch('POST','/api/auth/handoff',{'code':link['code']})
