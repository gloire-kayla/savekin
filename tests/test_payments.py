import copy
import json
import os
import tempfile
import unittest
import threading
from unittest.mock import patch
from datetime import date
import savekin as sk
import payments as pay

class PaymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old_db=sk.core.DB; self.old_mode=sk.core.MODE
        sk.core.DB=sk.core.Path(self.temp.name)/'payments.sqlite3'; sk.core.MODE='sandbox'
        with sk.core.connect() as db: db.executescript(sk.SCHEMA)
        self.a=sk.dispatch('POST','/api/auth/register',{'name':'Payer','email':'payer@example.com','password':'test-password-unique'})['token']
        self.b=sk.dispatch('POST','/api/auth/register',{'name':'Other','email':'other@example.com','password':'test-password-unique'})['token']
        self.gid=sk.dispatch('POST','/api/groups',{'name':'Recovery group','currency':'USD','sharePrice':'1','goal':'10',
            'shares':'2','end':date.today().isoformat(),'fine':'0','exitPenalty':'0'},self.a)['id']
        snap=self.snap(); self.member=snap['members'][0]; self.cycle=snap['cycle']
        with sk.core.connect() as db:
            db.execute('INSERT INTO sk_orders VALUES(?,?,?,?,?,?,0)',('ORDER1',self.gid,self.cycle['id'],self.member['id'],self.member['user_id'],250))
            db.execute('INSERT INTO sk_payment_state(order_id,recipient,status,updated) VALUES(?,?,?,?)',('ORDER1','treasurer@example.com','created',sk.core.now()))
        self.capture={'id':'CAPTURE1','status':'COMPLETED','amount':{'currency_code':'USD','value':'2.50'},
            'seller_receivable_breakdown':{'paypal_fee':{'currency_code':'USD','value':'0.10'}}}
        self.order={'id':'ORDER1','status':'COMPLETED','purchase_units':[{'payee':{'email_address':'treasurer@example.com'},
            'amount':{'currency_code':'USD','value':'2.50'},'payments':{'captures':[self.capture],'refunds':[]}}]}
        self.refunds={}; self.verify=True
        self.calls=[]
        self.mock=patch.object(sk.core,'paypal',side_effect=self.provider); self.mock.start()
        self.env=patch.dict(os.environ,{'PAYPAL_WEBHOOK_ID':'WH-CONFIG'}); self.env.start()

    def tearDown(self):
        self.env.stop(); self.mock.stop(); sk.core.DB=self.old_db; sk.core.MODE=self.old_mode; self.temp.cleanup()

    def provider(self,path,payload=None,token=None,request_id=None,method=None):
        self.calls.append((path,payload,method))
        if path=='/v1/oauth2/token': return {'access_token':'test-token'}
        if path=='/v1/notifications/verify-webhook-signature': return {'verification_status':'SUCCESS' if self.verify else 'FAILURE'}
        if path=='/v2/checkout/orders/ORDER1':
            self.assertEqual(method,'GET'); return copy.deepcopy(self.order)
        if path=='/v2/payments/captures/CAPTURE1':
            return {**copy.deepcopy(self.capture),'supplementary_data':{'related_ids':{'order_id':'ORDER1'}}}
        if path.startswith('/v2/payments/refunds/'):
            return copy.deepcopy(self.refunds[path.rsplit('/',1)[-1]])
        raise AssertionError('Unexpected provider call: '+path)

    def snap(self): return sk.dispatch('GET','/api/state',{},self.a)['groups'][0]
    def recover(self,token=None): return sk.dispatch('POST','/api/paypal/reconcile',{'groupId':self.gid,'orderId':'ORDER1'},token or self.a)
    def headers(self): return {'PAYPAL-AUTH-ALGO':'SHA256withRSA','PAYPAL-CERT-URL':'https://api.paypal.com/cert.pem',
        'PAYPAL-TRANSMISSION-ID':'TRANSMISSION1','PAYPAL-TRANSMISSION-SIG':'signature','PAYPAL-TRANSMISSION-TIME':'2026-11-06T00:00:00Z'}
    def event(self,kind='PAYMENT.CAPTURE.COMPLETED',eid='WH-EVENT1',refund=False):
        return {'id':eid,'event_type':kind,'resource_type':'refund' if refund else 'capture',
            'resource':{'id':'REFUND1' if refund else 'CAPTURE1','supplementary_data':{'related_ids':{'order_id':'ORDER1'}}}}
    def add_refund(self,gross='1.00',debit='0.95',rid='REFUND1'):
        self.refunds[rid]={'id':rid,'status':'COMPLETED','amount':{'currency_code':'USD','value':gross},
            'seller_payable_breakdown':{'net_amount':{'currency_code':'USD','value':debit}},
            'links':[{'rel':'up','href':'https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURE1'}]}
        self.order['purchase_units'][0]['payments']['refunds'].append({'id':rid,'status':'COMPLETED'})

    def test_recovery_credits_completed_order_once(self):
        self.assertTrue(self.recover()['credited']); self.recover()
        snap=self.snap(); self.assertEqual(snap['gross'],240); self.assertEqual(snap['pool'],240)
        self.assertEqual(len([e for e in snap['ledger'] if e['kind']=='contribution']),1)

    def test_refresh_and_repeated_checks_preserve_single_contribution(self):
        self.recover()
        for _ in range(3):
            self.assertEqual(self.snap()['pool'],240)
            self.recover()
        self.assertEqual(len([e for e in self.snap()['ledger'] if e['kind']=='contribution']),1)

    def test_abandoned_or_voided_checkout_never_adds_money(self):
        # Closing checkout can leave a CREATED order; cancellation need not void it.
        self.order['purchase_units'][0]['payments']['captures']=[]
        for status in ('CREATED','PAYER_ACTION_REQUIRED','VOIDED'):
            with self.subTest(status=status):
                self.order['status']=status
                self.assertFalse(self.recover()['credited'])
                self.assertEqual(self.snap()['pool'],0)
                self.assertEqual(self.snap()['ledger'],[])
        self.assertFalse(any(path.endswith('/capture') for path,_,_ in self.calls))

    def test_member_cannot_recover_someone_elses_order(self):
        with self.assertRaises(sk.Problem): self.recover(self.b)
        self.assertEqual(self.calls,[])

    def test_mismatched_recipient_or_amount_never_credits(self):
        self.order['purchase_units'][0]['payee']['email_address']='attacker@example.com'
        with self.assertRaises(sk.Problem): self.recover()
        self.assertEqual(self.snap()['ledger'],[])
        self.order['purchase_units'][0]['payee']['email_address']='treasurer@example.com'
        self.capture['amount']['value']='3.00'
        with self.assertRaises(sk.Problem): self.recover()
        self.assertEqual(self.snap()['ledger'],[])

    def test_pending_payment_is_visible_without_credit(self):
        self.capture['status']='PENDING'
        self.assertEqual(self.recover()['status'],'pending'); self.assertEqual(self.snap()['gross'],0)
        self.assertEqual(self.snap()['paymentOrders'][0]['status'],'pending')

    def test_approved_order_does_not_capture_during_status_check(self):
        self.order['status']='APPROVED'; self.order['purchase_units'][0]['payments']['captures']=[]
        self.assertEqual(self.recover()['status'],'approved')
        self.assertFalse(any(path.endswith('/capture') for path,_,_ in self.calls))

    def test_verified_webhook_replay_is_idempotent(self):
        self.assertTrue(pay.webhook(self.headers(),self.event())['ok'])
        self.assertTrue(pay.webhook(self.headers(),self.event())['duplicate'])
        self.assertEqual(self.snap()['gross'],240)
        self.assertEqual(len([c for c in self.calls if c[0]=='/v2/checkout/orders/ORDER1']),1)

    def test_invalid_signature_or_missing_headers_never_mutates(self):
        self.verify=False
        with self.assertRaises(sk.Problem): pay.webhook(self.headers(),self.event())
        with self.assertRaises(sk.Problem): pay.webhook({},self.event())
        with sk.core.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM sk_webhook_events').fetchone()[0],0)
        self.assertEqual(self.snap()['ledger'],[])

    def test_untrusted_certificate_url_is_not_fetched(self):
        headers=self.headers(); headers['PAYPAL-CERT-URL']='http://127.0.0.1/private'
        with self.assertRaises(sk.Problem): pay.webhook(headers,self.event())
        self.assertEqual(self.calls,[])

    def test_refund_before_completion_event_recovers_both_without_double_credit(self):
        self.add_refund(); self.capture['status']='PARTIALLY_REFUNDED'
        pay.webhook(self.headers(),self.event('PAYMENT.CAPTURE.REFUNDED',refund=True))
        pay.webhook(self.headers(),self.event(eid='WH-EVENT2'))
        snap=self.snap(); self.assertEqual(snap['gross'],145); self.assertEqual(snap['pool'],145)
        self.assertEqual(snap['paymentOrders'][0]['status'],'partially_refunded')
        self.assertEqual(len([e for e in snap['ledger'] if e['kind']=='refund']),1)

    def test_full_refund_with_nonreturned_fee_preserves_loss(self):
        self.add_refund('2.50','2.50'); self.capture['status']='REFUNDED'
        self.recover(); snap=self.snap()
        self.assertEqual(snap['gross'],0); self.assertEqual(snap['pool'],-10)
        self.assertEqual(sum(e['amount'] for e in snap['ledger'] if e['kind']=='refund_cost'),10)

    def test_late_refund_invalidates_approved_settlement(self):
        self.recover()
        with sk.core.connect() as db:
            db.execute("UPDATE sk_cycles SET status='approved',settlement=? WHERE id=?",(json.dumps({'allocations':[]}),self.cycle['id']))
            db.execute('INSERT INTO sk_proposals VALUES(?,?,?,?,?,?,?,?)',('SETTLE1',self.gid,'settlement','{}','accepted',sk.core.now(),self.cycle['id'],'[]'))
        self.add_refund(); self.capture['status']='PARTIALLY_REFUNDED'; self.recover()
        snap=self.snap(); self.assertEqual(snap['cycle']['status'],'open'); self.assertIsNone(snap['cycle']['settlement'])
        self.assertEqual(snap['proposals'][0]['status'],'invalidated')

    def test_refund_after_distribution_flags_review_instead_of_reopening(self):
        self.recover()
        with sk.core.connect() as db: db.execute("UPDATE sk_cycles SET status='distributed' WHERE id=?",(self.cycle['id'],))
        self.add_refund(); self.capture['status']='PARTIALLY_REFUNDED'; self.recover()
        self.assertEqual(self.snap()['cycle']['status'],'reconciliation_required'); self.assertFalse(self.snap()['canSettle'])

    def test_reversal_replay_and_later_refund_do_not_double_deduct(self):
        pay.webhook(self.headers(),self.event('PAYMENT.CAPTURE.REVERSED'))
        pay.webhook(self.headers(),self.event('PAYMENT.CAPTURE.REVERSED','WH-EVENT2'))
        self.assertEqual(self.snap()['gross'],0)
        self.add_refund(); pay.webhook(self.headers(),self.event('PAYMENT.CAPTURE.REFUNDED','WH-EVENT3',True))
        self.assertEqual(self.snap()['gross'],0); self.assertEqual(self.snap()['paymentOrders'][0]['needs_review'],1)

    def test_failed_verification_can_be_retried(self):
        self.verify=False
        with self.assertRaises(sk.Problem): pay.webhook(self.headers(),self.event())
        self.verify=True; pay.webhook(self.headers(),self.event())
        self.assertEqual(self.snap()['gross'],240)

    def test_missing_fee_blocks_credit_until_provider_details_arrive(self):
        del self.capture['seller_receivable_breakdown']
        self.assertFalse(self.recover()['credited']); self.assertEqual(self.snap()['gross'],0)
        self.assertEqual(self.snap()['paymentOrders'][0]['needs_review'],1)
        self.capture['seller_receivable_breakdown']={'paypal_fee':{'currency_code':'USD','value':'0.10'}}
        self.assertTrue(self.recover()['credited']); self.assertEqual(self.snap()['gross'],240)
        self.assertEqual(self.snap()['paymentOrders'][0]['needs_review'],0)

    def test_stale_pending_status_does_not_downgrade_completed_payment(self):
        self.recover(); self.capture['status']='PENDING'
        self.assertEqual(self.recover()['status'],'completed'); self.assertEqual(self.snap()['gross'],240)

    def test_provider_failure_does_not_consume_event_or_credit_money(self):
        original=self.provider
        def fail(path,*args,**kwargs):
            if path=='/v2/checkout/orders/ORDER1': raise TimeoutError('provider unavailable')
            return original(path,*args,**kwargs)
        with patch.object(sk.core,'paypal',side_effect=fail):
            with self.assertRaises(TimeoutError): pay.webhook(self.headers(),self.event())
        with sk.core.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM sk_webhook_events').fetchone()[0],0)
        self.assertEqual(self.snap()['ledger'],[])
        self.assertTrue(pay.webhook(self.headers(),self.event())['ok'])

    def test_missing_webhook_configuration_fails_closed(self):
        with patch.dict(os.environ,{'PAYPAL_WEBHOOK_ID':''}):
            with self.assertRaises(sk.Problem): pay.webhook(self.headers(),self.event())
        self.assertEqual(self.snap()['ledger'],[])

    def test_concurrent_callback_and_event_cannot_double_credit(self):
        barrier=threading.Barrier(2); errors=[]
        def apply():
            try:
                with sk.core.connect() as db:
                    order=sk.row(db,'SELECT * FROM sk_orders WHERE id=?',('ORDER1',))
                    barrier.wait(timeout=3)
                    pay.record_capture(db,order,self.order['purchase_units'][0],self.capture,'test')
            except Exception as exc: errors.append(exc)
        threads=[threading.Thread(target=apply) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=8)
        self.assertFalse(any(thread.is_alive() for thread in threads)); self.assertEqual(errors,[])
        self.assertEqual(self.snap()['gross'],240)
        self.assertEqual(len([e for e in self.snap()['ledger'] if e['kind']=='contribution']),1)

if __name__=='__main__': unittest.main()
