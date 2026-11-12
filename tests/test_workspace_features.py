import base64
import os
import unittest
from unittest.mock import patch
import savekin as sk
import account_features as accounts
import test_savekin as fixtures


class WorkspaceTests(unittest.TestCase):
    setUp=fixtures.SaveKinTests.setUp
    tearDown=fixtures.SaveKinTests.tearDown
    register=fixtures.SaveKinTests.register
    call=fixtures.SaveKinTests.call
    group=fixtures.SaveKinTests.group
    join=fixtures.SaveKinTests.join
    elect=fixtures.SaveKinTests.elect
    snap=fixtures.SaveKinTests.snap

    def state(self,token=None): return sk.dispatch('GET','/api/state',{},token or self.a)

    def user(self,token): return self.state(token)['user']['id']

    def setup_circle(self):
        gid=self.group(); self.elect(gid); self.join(gid,self.c)
        return gid

    def replacement(self,gid):
        pid=self.call('/api/proposals',{'groupId':gid,'kind':'treasurer','userId':self.user(self.c)})['proposalId']
        for token in (self.a,self.b,self.c):
            if self.snap(gid)['treasury']['handover']: break
            self.call('/api/vote',{'groupId':gid,'proposalId':pid,'approve':True},token)
        return self.snap(gid)['treasury']['handover']

    def prepare(self,gid):
        if self.snap(gid)['treasury']['handover']['status']=='setup':
            self.call('/api/treasury/account',{'groupId':gid,'email':'new-treasury@example.com','confirm':True},self.c)
        self.call('/api/treasury/statement',{'groupId':gid,'amount':str(self.snap(gid)['pool']/100),'fees':'0.10','feePayer':'Outgoing treasurer separately','note':'Checked group funds and statement.'},self.b)

    def approve_terms(self,gid):
        for token in (self.a,self.b,self.c): self.call('/api/treasury/statement-vote',{'groupId':gid,'approve':True},token)

    def test_profile_is_private_validates_photos_and_changes_name(self):
        photo='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nexample').decode()
        self.call('/api/profile',{'name':'Alice updated','photo':photo})
        self.assertEqual(self.state()['user']['name'],'Alice updated')
        self.assertEqual(self.state()['profile']['photo'],photo)
        self.assertIsNone(self.state(self.b)['profile']['photo'])
        for value in ('data:image/svg+xml;base64,PHN2Zy8+', 'https://example.com/photo.png', 'data:image/png;base64,%%%'):
            with self.assertRaises(sk.Problem): self.call('/api/profile',{'photo':value})
        self.call('/api/profile',{'photo':None})
        self.assertIsNone(self.state()['profile']['photo'])

    def test_password_change_requires_current_and_invalidates_other_sessions(self):
        other=self.call('/api/auth/login',{'email':'alice@example.com','password':'unique-test-password-123'})['token']
        with self.assertRaises(sk.Problem): self.call('/api/profile/password',{'currentPassword':'wrong','password':'new-long-password-123'})
        self.call('/api/profile/password',{'currentPassword':'unique-test-password-123','password':'new-long-password-123'})
        self.state()
        with self.assertRaises(sk.Problem): self.state(other)
        with self.assertRaises(sk.Problem): self.call('/api/auth/login',{'email':'alice@example.com','password':'unique-test-password-123'})
        self.call('/api/auth/login',{'email':'alice@example.com','password':'new-long-password-123'})

    def test_email_change_waits_for_valid_single_use_code(self):
        with patch.object(accounts,'deliver',return_value='email') as mail:
            self.call('/api/profile/email-request',{'email':'new@example.com','currentPassword':'unique-test-password-123'})
            code=mail.call_args.args[1]
        self.assertEqual(self.state()['user']['email'],'alice@example.com')
        wrong='000001' if code!='000001' else '000002'
        self.assertFalse(self.call('/api/profile/email-confirm',{'code':wrong})['ok'])
        self.assertTrue(self.call('/api/profile/email-confirm',{'code':code})['ok'])
        self.assertEqual(self.state()['user']['email'],'new@example.com')
        self.assertTrue(self.state()['profile']['emailVerified'])
        self.assertFalse(self.call('/api/profile/email-confirm',{'code':code})['ok'])

    def test_verification_attempt_limit_is_committed(self):
        with patch.object(accounts,'deliver',return_value='email') as mail:
            self.call('/api/profile/email-request',{'email':'alice@example.com','currentPassword':'unique-test-password-123'})
            code=mail.call_args.args[1]
        wrong='111111' if code!='111111' else '222222'
        for _ in range(5): self.assertFalse(self.call('/api/profile/email-confirm',{'code':wrong})['ok'])
        self.assertFalse(self.call('/api/profile/email-confirm',{'code':code})['ok'])

    def test_recovery_is_single_use_expires_and_revokes_sessions(self):
        with patch.object(accounts,'deliver',return_value='email') as mail:
            existing=self.call('/api/auth/forgot-password',{'email':'alice@example.com'})
            code=mail.call_args.args[1]
            unknown=self.call('/api/auth/forgot-password',{'email':'nobody@example.com'})
        self.assertEqual(existing,unknown)
        result=self.call('/api/auth/reset-password',{'email':'alice@example.com','code':code,'password':'changed-password-123'})
        self.assertTrue(result['ok'])
        with self.assertRaises(sk.Problem): self.state()
        self.assertFalse(self.call('/api/auth/reset-password',{'email':'alice@example.com','code':code,'password':'other-password-123'})['ok'])
        token=self.call('/api/auth/login',{'email':'alice@example.com','password':'changed-password-123'})['token']
        with patch.object(accounts,'deliver',return_value='email') as mail:
            self.call('/api/auth/forgot-password',{'email':'alice@example.com'})
            code=mail.call_args.args[1]
        with sk.core.connect() as db: db.execute('UPDATE sk_email_codes SET expires=0')
        self.assertFalse(self.call('/api/auth/reset-password',{'email':'alice@example.com','code':code,'password':'other-password-123'})['ok'])
        self.state(token)

    def test_discussions_isolate_groups_idempotency_and_preserve_attribution(self):
        gid=self.group();self.join(gid,self.b)
        body={'groupId':gid,'action':'send','message':'Hello <script>group</script>','clientId':'message-1'}
        first=self.call('/api/discussions',body);self.assertEqual(self.call('/api/discussions',body),first)
        with self.assertRaises(sk.Problem): self.call('/api/discussions',{'groupId':gid},self.c)
        self.call('/api/profile',{'name':'Changed name'})
        messages=self.call('/api/discussions',{'groupId':gid},self.b)['messages']
        self.assertEqual(len(messages),1);self.assertEqual(messages[0]['sender_name'],'Alice')
        with sk.core.connect() as db: db.execute("UPDATE sk_members SET status='left' WHERE group_id=? AND user_id=?",(gid,self.user(self.b)))
        with self.assertRaises(sk.Problem): self.call('/api/discussions',{'groupId':gid},self.b)
        self.assertEqual(self.call('/api/discussions',{'groupId':gid})['messages'][0]['content'],body['message'])

    def test_unread_notifications_only_mark_messages_actually_seen(self):
        gid=self.group();self.join(gid,self.b)
        first=self.call('/api/discussions',{'groupId':gid,'action':'send','message':'First','clientId':'one'})
        self.call('/api/discussions',{'groupId':gid,'action':'send','message':'Second','clientId':'two'})
        items=self.call('/api/notifications',{},self.b)['items']
        self.assertTrue(any(n['page']=='discussions' and n['unread'] for n in items))
        self.call('/api/discussions',{'groupId':gid,'action':'read','through':first['id']},self.b)
        self.assertTrue(any(n['page']=='discussions' and n['unread'] for n in self.call('/api/notifications',{},self.b)['items']))
        latest=self.call('/api/discussions',{'groupId':gid},self.b)['messages'][-1]['id']
        self.call('/api/discussions',{'groupId':gid,'action':'read','through':latest},self.b)
        self.assertFalse(any(n['page']=='discussions' for n in self.call('/api/notifications',{},self.b)['items']))

    def test_handover_pauses_money_until_terms_and_receipts_complete(self):
        gid=self.setup_circle();self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        old=self.user(self.b);new=self.user(self.c);h=self.replacement(gid)
        self.assertEqual(h['status'],'setup');self.assertEqual(self.snap(gid)['treasurer'],old)
        for path,body in (('/api/contribute',{'amount':'1'}),('/api/shares',{'shares':'3','when':'next'}),('/api/proposals',{'kind':'settlement'})):
            with self.assertRaises(sk.Problem): self.call(path,{'groupId':gid,**body})
        self.assertFalse(self.snap(gid)['canSettle'])
        self.prepare(gid)
        with self.assertRaises(sk.Problem): self.call('/api/treasury/transfer',{'groupId':gid,'reference':'external-1','confirm':True},self.b)
        self.approve_terms(gid)
        self.call('/api/treasury/transfer',{'groupId':gid,'reference':'external-1','confirm':True},self.b)
        with self.assertRaises(sk.Problem): self.call('/api/treasury/confirm',{'groupId':gid,'confirm':True},self.b)
        self.call('/api/treasury/confirm',{'groupId':gid,'confirm':True},self.c)
        self.assertEqual(self.snap(gid)['treasurer'],old)
        self.call('/api/treasury/confirm',{'groupId':gid,'confirm':True})
        snap=self.snap(gid);self.assertEqual(snap['treasurer'],new);self.assertEqual(snap['pool'],200)
        self.assertEqual(snap['treasury']['handover']['status'],'complete')
        self.assertEqual(len(snap['ledger']),1)

    def test_handover_rejects_discrepancies_and_revision_clears_votes(self):
        gid=self.setup_circle();self.call('/api/contribute',{'groupId':gid,'amount':'2'});self.replacement(gid)
        self.call('/api/treasury/account',{'groupId':gid,'email':'new@example.com','confirm':True},self.c)
        with self.assertRaises(sk.Problem): self.call('/api/treasury/statement',{'groupId':gid,'amount':'1','fees':'0','feePayer':'Me','note':'Missing funds'},self.b)
        self.prepare(gid);self.approve_terms(gid);self.prepare(gid)
        self.assertEqual(self.snap(gid)['treasury']['votes'],[])
        with self.assertRaises(sk.Problem): self.call('/api/treasury/account',{'groupId':gid,'email':'other@example.com','confirm':True},self.c)

    def test_handover_waits_for_pending_orders_and_sandbox_destination(self):
        gid=self.setup_circle();self.replacement(gid)
        self.call('/api/treasury/account',{'groupId':gid,'email':'new-treasury@example.com','confirm':True},self.c)
        with sk.core.connect() as db:
            cycle=sk.current(db,gid);member=sk.row(db,'SELECT id FROM sk_members WHERE group_id=? AND user_id=?',(gid,self.user(self.a)))
            db.execute('INSERT INTO sk_orders VALUES(?,?,?,?,?,?,0)',('pending-order',gid,cycle['id'],member['id'],self.user(self.a),100))
        with self.assertRaises(sk.Problem): self.prepare(gid)
        with sk.core.connect() as db: db.execute('INSERT INTO sk_payment_state(order_id,recipient,status,updated) VALUES(?,?,?,?)',('pending-order','old@example.com','failed',sk.core.now()))
        self.prepare(gid);self.approve_terms(gid)
        self.call('/api/treasury/transfer',{'groupId':gid,'reference':'external-zero','confirm':True},self.b)
        sk.core.MODE='sandbox'
        self.call('/api/treasury/confirm',{'groupId':gid,'confirm':True},self.c)
        response=self.call('/api/treasury/confirm',{'groupId':gid,'confirm':True})
        self.assertIn('configuration',response['message']);self.assertEqual(self.snap(gid)['treasurer'],self.user(self.b))
        with patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'new-treasury@example.com'}):
            self.call('/api/treasury/confirm',{'groupId':gid,'confirm':True})
            self.assertEqual(self.snap(gid)['treasurer'],self.user(self.c))

    def test_receiving_email_does_not_require_matching_login_or_allow_silent_switch(self):
        gid=self.setup_circle()
        self.call('/api/treasury/account',{'groupId':gid,'email':'separate-business@example.com','confirm':True},self.b)
        with patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'separate-business@example.com'}):
            self.assertTrue(self.snap(gid)['treasury']['receiving']['ready'])
        self.call('/api/contribute',{'groupId':gid,'amount':'2'})
        with self.assertRaises(sk.Problem): self.call('/api/treasury/account',{'groupId':gid,'email':'switched@example.com','confirm':True},self.b)

    def test_new_treasurer_needs_account_declaration_before_checkout(self):
        gid=self.group(); self.join(gid,self.b)
        pid=self.call('/api/proposals',{'groupId':gid,'kind':'treasurer','userId':self.user(self.b)})['proposalId']
        for token in (self.a,self.b): self.call('/api/vote',{'groupId':gid,'proposalId':pid,'approve':True},token)
        sk.core.MODE='sandbox'
        with patch.dict(os.environ,{'PAYPAL_TREASURER_EMAIL':'bob@example.com'}),patch.object(sk.core,'paypal') as paypal:
            with self.assertRaises(sk.Problem): self.call('/api/paypal/orders',{'groupId':gid,'amount':'1'})
            paypal.assert_not_called()
        self.assertFalse(self.snap(gid)['treasury']['receiving']['declared'])

    def test_changing_login_email_keeps_declared_receiving_destination(self):
        gid=self.setup_circle()
        with patch.object(accounts,'deliver',return_value='email') as mail:
            self.call('/api/profile/email-request',{'email':'bob-new@example.com','currentPassword':'unique-test-password-123'},self.b)
            code=mail.call_args.args[1]
        self.call('/api/profile/email-confirm',{'code':code},self.b)
        self.assertEqual(self.state(self.b)['user']['email'],'bob-new@example.com')
        self.assertEqual(self.snap(gid)['treasury']['receiving']['email'],'bob@example.com')


if __name__=='__main__': unittest.main()
