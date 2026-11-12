import base64
import io
import json
import os
import unittest
from unittest.mock import patch
import savekin as sk
import fees
import test_savekin as fixtures


class TreasuryAndFeeTests(unittest.TestCase):
    setUp=fixtures.SaveKinTests.setUp
    tearDown=fixtures.SaveKinTests.tearDown
    register=fixtures.SaveKinTests.register
    call=fixtures.SaveKinTests.call
    group=fixtures.SaveKinTests.group
    snap=fixtures.SaveKinTests.snap
    join=fixtures.SaveKinTests.join
    elect=fixtures.SaveKinTests.elect

    def request(self,gid,**extra):
        return self.call('/api/proposals',{'groupId':gid,'kind':'treasury','amount':'1',
            'reference':'Own-allocation-1','note':'Personal funds already in treasury, set aside for this group.',
            'confirmOwnFunds':True,**extra},self.b)['proposalId']

    def test_treasury_is_credited_only_after_separate_president_confirmation(self):
        gid=self.group(); self.elect(gid); pid=self.request(gid)
        self.assertEqual(self.snap(gid)['pool'],0)
        with self.assertRaises(sk.Problem): self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True},self.b)
        with self.assertRaises(sk.Problem): self.call('/api/approve',{'groupId':gid,'proposalId':pid})
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        snap=self.snap(gid)
        self.assertEqual(snap['pool'],100)
        self.assertEqual(next(m for m in snap['members'] if m['name']=='Bob')['arrears'],0)
        self.assertEqual(snap['ledger'][0]['kind'],'treasury_contribution')
        with self.assertRaises(sk.Problem): self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        self.assertEqual(self.snap(gid)['pool'],100)
        with self.assertRaises(sk.Problem): self.request(gid)

    def test_rejection_does_not_credit_money(self):
        gid=self.group(); self.elect(gid); pid=self.request(gid)
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':False})
        self.assertEqual(self.snap(gid)['ledger'],[])
        self.assertEqual(self.snap(gid)['proposals'][0]['status'],'rejected')

    def test_evidence_validation_and_group_isolation(self):
        gid=self.group(); self.elect(gid)
        with self.assertRaises(sk.Problem):
            self.request(gid,evidence={'name':'bad.png','mime':'image/png','data':base64.b64encode(b'not PNG').decode()})
        self.assertFalse(any(p['kind']=='treasury' for p in self.snap(gid)['proposals']))
        data=b'%PDF-1.4\nTest evidence'
        pid=self.request(gid,evidence={'name':'evidence.pdf','mime':'application/pdf','data':base64.b64encode(data).decode()})
        evidence=self.call('/api/treasury/evidence',{'groupId':gid,'proposalId':pid})
        self.assertEqual(base64.b64decode(evidence['data']),data)
        with self.assertRaises(sk.Problem): self.call('/api/treasury/evidence',{'groupId':gid,'proposalId':pid},self.c)

    def test_pending_treasury_request_blocks_settlement_and_officer_changes(self):
        gid=self.group(); self.elect(gid)
        self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        self.call('/api/contribute',{'groupId':gid,'amount':'1'},self.b)
        self.request(gid)
        self.assertFalse(self.snap(gid)['canSettle'])
        with self.assertRaises(sk.Problem): self.call('/api/proposals',{'groupId':gid,'kind':'settlement'})
        with self.assertRaises(sk.Problem): self.call('/api/proposals',{'groupId':gid,'kind':'treasurer','userId':self.snap(gid)['treasurer']})

    def test_manual_contribution_counts_toward_goal_without_claiming_paypal_capture(self):
        gid=self.group(ending='goal',goal='1'); self.elect(gid)
        pid=self.request(gid)
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        snap=self.snap(gid)
        self.assertEqual(snap['cycle']['status'],'goal_reached')
        self.assertEqual(snap['paymentOrders'],[])

    def test_ai_sees_manual_totals_without_supporting_evidence_or_reference(self):
        gid=self.group(); self.elect(gid); pid=self.request(gid,note='Private supporting note xyz')
        self.call('/api/approve',{'groupId':gid,'proposalId':pid,'approve':True})
        fake={'output':[{'type':'message','content':[{'type':'output_text','text':'Your treasury contribution was manually confirmed.'}]}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'mock','OPENAI_MODEL':'mock'}),patch.object(sk.core.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(fake).encode())) as http:
            self.call('/api/assistant',{'groupId':gid,'question':'Explain my contribution','consent':True},self.b)
            payload=json.loads(http.call_args.args[0].data)
            records=json.loads(payload['input'][0]['content'])['records']
            self.assertEqual(records['yourContributionSources']['manuallyConfirmedTreasury'],100)
            self.assertNotIn('Private supporting note xyz',json.dumps(payload['input']))
            self.assertNotIn('Own-allocation-1',json.dumps(payload['input']))

    def test_minimum_gross_estimate_uses_fee_on_total_and_cent_rounding(self):
        with patch.dict(os.environ,{'PAYPAL_FEE_BPS':'349','PAYPAL_FEE_FIXED_CENTS':'49'}):
            self.assertEqual(fees.estimate(400)['gross'],465)
            for target in (1,49,100,400,10000,1000000):
                q=fees.estimate(target)
                self.assertGreaterEqual(q['estimatedNet'],target)
                previous=q['gross']-1
                previous_fee=(previous*349+5000)//10000+49
                self.assertLess(previous-previous_fee,target)

    def test_quote_is_bound_to_member_amount_and_expiry_and_reuses_order(self):
        gid=self.group(); self.elect(gid); sk.core.MODE='sandbox'
        q=self.call('/api/paypal/quote',{'groupId':gid,'amount':'4'})
        with patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'bob@example.com'}),patch.object(sk.core,'paypal',side_effect=[{'access_token':'test'},{'id':'QUOTED1'}]) as provider:
            for token,amount in ((self.b,'4'),(self.a,'5')):
                with self.assertRaises(sk.Problem): self.call('/api/paypal/orders',{'groupId':gid,'amount':amount,'quoteId':q['quoteId']},token)
            payload={'groupId':gid,'amount':'4','quoteId':q['quoteId']}
            self.assertEqual(self.call('/api/paypal/orders',payload)['id'],'QUOTED1')
            self.assertEqual(self.call('/api/paypal/orders',payload)['id'],'QUOTED1')
            self.assertEqual(provider.call_count,2)
            sent=provider.call_args.args[1]
            self.assertEqual(sent['purchase_units'][0]['amount']['value'],f"{q['gross']/100:.2f}")
        q=self.call('/api/paypal/quote',{'groupId':gid,'amount':'4'})
        with patch.object(sk.time,'time',return_value=sk.time.time()+601),patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'bob@example.com'}):
            with self.assertRaises(sk.Problem): self.call('/api/paypal/orders',{'groupId':gid,'amount':'4','quoteId':q['quoteId']})

    def test_actual_fee_difference_is_reported_without_inventing_savings(self):
        import payments
        gid=self.group(); self.elect(gid); sk.core.MODE='sandbox'
        q=self.call('/api/paypal/quote',{'groupId':gid,'amount':'4'})
        with patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'bob@example.com'}),patch.object(sk.core,'paypal',side_effect=[{'access_token':'mock'},{'id':'FEEORDER'}]):
            self.call('/api/paypal/orders',{'groupId':gid,'amount':'4','quoteId':q['quoteId']})
        with sk.core.connect() as db:
            order=sk.row(db,'SELECT * FROM sk_orders WHERE id=?',('FEEORDER',))
            result=payments.record_capture(db,order,{'payee':{'email_address':'bob@example.com'}},
                {'id':'FEECAP','status':'COMPLETED','amount':{'currency_code':'USD','value':f"{q['gross']/100:.2f}"},
                 'seller_receivable_breakdown':{'paypal_fee':{'currency_code':'USD','value':'0.70'}}},'test')
        self.assertEqual(result['net'],q['gross']-70)
        self.assertEqual(result['shortfall'],max(0,400-result['net']))
        self.assertEqual(self.snap(gid)['pool'],result['net'])
