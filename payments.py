"""PayPal sandbox recovery and verified event reconciliation. Never initiates refunds/payouts."""
import json
import re
from urllib.parse import urlparse
import server as core
import savekin as sk

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value):
        raise sk.Problem('Invalid provider reference.')
    return value

def dollars(value):
    if not isinstance(value,dict) or value.get('currency_code')!='USD':
        raise sk.Problem('Provider amount is not in the expected USD currency.')
    return sk.money(value.get('value'),zero=True)

def payment_state(db,order):
    state=sk.row(db,'SELECT * FROM sk_payment_state WHERE order_id=?',(order['id'],))
    if not state:
        # Legacy orders use the current configured recipient, never an email from an incoming event.
        recipient=core.os.environ.get('PAYPAL_TREASURER_EMAIL','').strip().lower()
        if not recipient: raise sk.Problem('Configure the sandbox recipient before recovering this order.',503)
        db.execute('INSERT INTO sk_payment_state(order_id,recipient,status,updated) VALUES(?,?,?,?)',
            (order['id'],recipient,'created',core.now()))
        state=sk.row(db,'SELECT * FROM sk_payment_state WHERE order_id=?',(order['id'],))
    return state

def entry(db,order,kind,value,reference):
    if value:
        db.execute('INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)',
            (sk.uid(),order['group_id'],order['cycle_id'],order['member_id'],kind,value,reference,core.now()))

def invalidate(db,order,actor,reason):
    cycle=sk.row(db,'SELECT * FROM sk_cycles WHERE id=?',(order['cycle_id'],))
    if cycle['status'] in ('review','approved'):
        db.execute("UPDATE sk_cycles SET status='open',settlement=NULL WHERE id=?",(cycle['id'],))
        db.execute("UPDATE sk_proposals SET status='invalidated' WHERE cycle_id=? AND kind='settlement' AND status IN ('pending','accepted')",(cycle['id'],))
    elif cycle['status'] in ('paying','distributed','reconciliation_required'):
        db.execute("UPDATE sk_cycles SET status='reconciliation_required' WHERE id=?",(cycle['id'],))
        db.execute("UPDATE sk_payment_state SET needs_review=1,review_reason='distributed_cycle_changed' WHERE order_id=?",(order['id'],))
    if sk.row(db,"SELECT id FROM sk_ledger WHERE member_id=? AND cycle_id=? AND kind='exit_principal'",(order['member_id'],cycle['id'])):
        db.execute("UPDATE sk_payment_state SET needs_review=1,review_reason='exited_member_payment_changed' WHERE order_id=?",(order['id'],))
    # An exit approval must not survive a change to the member's underlying paid balance.
    proposals=sk.rows(db,"SELECT * FROM sk_proposals WHERE cycle_id=? AND kind='exit' AND status IN ('pending','accepted')",(cycle['id'],))
    for proposal in proposals:
        if json.loads(proposal['payload'])['memberId']==order['member_id']:
            db.execute("UPDATE sk_proposals SET status='invalidated' WHERE id=?",(proposal['id'],))
            db.execute("UPDATE sk_members SET status='active' WHERE id=? AND status IN ('exit_pending','exit_approved')",(order['member_id'],))
    sk.audit(db,order['group_id'],actor,reason)

def goal_status(db,order):
    group=sk.row(db,'SELECT * FROM sk_groups WHERE id=?',(order['group_id'],))
    rules=json.loads(group['rules'])
    cycle=sk.row(db,'SELECT * FROM sk_cycles WHERE id=?',(order['cycle_id'],))
    if rules['ending']!='goal' or cycle['status'] not in ('open','goal_reached'): return
    paid=db.execute("SELECT COALESCE(SUM(CASE WHEN kind IN ('contribution','treasury_contribution') THEN amount WHEN kind IN ('refund','reversal') THEN -amount ELSE 0 END),0) FROM sk_ledger WHERE cycle_id=?",(cycle['id'],)).fetchone()[0]
    db.execute('UPDATE sk_cycles SET status=? WHERE id=?',('goal_reached' if paid>=rules['goal'] else 'open',cycle['id']))

def record_capture(db,order,unit,capture,actor):
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    state=payment_state(db,order)
    capture_id=identifier(capture.get('id'))
    payee=unit.get('payee') or capture.get('payee') or {}
    if payee.get('email_address','').lower()!=state['recipient']:
        raise sk.Problem('Payment recipient does not match this order.')
    if dollars(capture.get('amount'))!=order['amount']:
        raise sk.Problem('Payment amount does not match this order.')
    if state['capture_id'] and state['capture_id']!=capture_id:
        raise sk.Problem('An unexpected additional capture requires manual review.')
    status=capture.get('status')
    if status in ('PENDING','DECLINED','FAILED'):
        if sk.row(db,'SELECT id FROM sk_ledger WHERE reference=?',(capture_id,)):
            return {'ok':not bool(state['needs_review']),'status':state['status'],'credited':True}
        local='pending' if status=='PENDING' else 'failed'
        db.execute('UPDATE sk_payment_state SET capture_id=?,status=?,updated=? WHERE order_id=?',
            (capture_id,local,core.now(),order['id']))
        return {'ok':False,'status':local,'credited':False}
    if status not in ('COMPLETED','PARTIALLY_REFUNDED','REFUNDED','REVERSED'):
        raise sk.Problem('Payment has not reached a recognized capture state.')
    fee=capture.get('seller_receivable_breakdown',{}).get('paypal_fee')
    if fee is None:
        db.execute("UPDATE sk_payment_state SET capture_id=?,status='review',needs_review=1,review_reason='missing_fee',updated=? WHERE order_id=?",
            (capture_id,core.now(),order['id']))
        return {'ok':False,'status':'review','credited':False}
    cost=dollars(fee)
    if cost>=order['amount']: raise sk.Problem('Provider fees are inconsistent with the payment.')
    net=order['amount']-cost
    existing=sk.row(db,'SELECT * FROM sk_ledger WHERE reference=?',(capture_id,))
    if existing and (existing['amount']!=net or existing['member_id']!=order['member_id'] or existing['cycle_id']!=order['cycle_id']):
        raise sk.Problem('The provider record conflicts with the recorded contribution.')
    if state.get('review_reason')=='missing_fee':
        db.execute('UPDATE sk_payment_state SET needs_review=0,review_reason=NULL WHERE order_id=?',(order['id'],))
    if not existing:
        entry(db,order,'contribution',net,capture_id)
        entry(db,order,'provider_fee',cost,'FEE-'+capture_id)
        invalidate(db,order,actor,'Verified sandbox contribution '+capture_id)
    db.execute('UPDATE sk_orders SET captured=1 WHERE id=?',(order['id'],))
    # A replayed completion event must not erase later refund/reversal status or a review hold.
    next_status=state['status'] if state['status'] in ('partially_refunded','refunded','reversed') else 'completed'
    db.execute('UPDATE sk_payment_state SET capture_id=?,status=?,updated=? WHERE order_id=?',
        (capture_id,next_status,core.now(),order['id']))
    goal_status(db,order)
    quote=sk.row(db,'SELECT target FROM sk_payment_quotes WHERE order_id=?',(order['id'],))
    return {'ok':True,'status':next_status,'credited':True,'net':net,'actualFee':cost,
        'target':quote['target'] if quote else None,
        'shortfall':max(0,quote['target']-net) if quote else 0}

def capture_link(resource):
    capture_id=resource.get('supplementary_data',{}).get('related_ids',{}).get('capture_id')
    if capture_id: return identifier(capture_id)
    for link in resource.get('links',[]):
        url=urlparse(link.get('href',''))
        match=re.fullmatch(r'/v2/payments/captures/([A-Za-z0-9_-]{1,80})',url.path)
        if link.get('rel')=='up' and url.scheme=='https' and url.hostname in (
            'api-m.sandbox.paypal.com','api.sandbox.paypal.com','api-m.paypal.com','api.paypal.com') and match:
            return match[1]
    raise sk.Problem('Refund is missing its verified capture reference.')

def refund(db,order,resource,actor):
    refund_id=identifier(resource.get('id'))
    if sk.row(db,'SELECT id FROM sk_payment_refunds WHERE id=?',(refund_id,)): return
    if resource.get('status')!='COMPLETED': return
    state=payment_state(db,order)
    if capture_link(resource)!=state['capture_id']: raise sk.Problem('Refund belongs to a different capture.')
    if state['status']=='reversed':
        reference='REFUND-AFTER-REVERSAL-'+refund_id
        if not sk.row(db,'SELECT id FROM sk_ledger WHERE reference=?',(reference,)):
            entry(db,order,'refund_review',dollars(resource.get('amount')),reference)
            sk.audit(db,order['group_id'],actor,'Refund after reversal needs manual reconciliation; no duplicate deduction made')
        return
    gross=dollars(resource.get('amount'))
    prior=db.execute('SELECT COALESCE(SUM(gross),0) FROM sk_payment_refunds WHERE order_id=?',(order['id'],)).fetchone()[0]
    if gross<=0 or prior+gross>order['amount']: raise sk.Problem('Refund total exceeds the original payment.')
    net=resource.get('seller_payable_breakdown',{}).get('net_amount')
    if net is None:
        # Preserve the known gross debit conservatively, but block settlement until reconciled.
        debit=gross
        db.execute("UPDATE sk_payment_state SET needs_review=1,review_reason='missing_refund_debit' WHERE order_id=?",(order['id'],))
    else:
        debit=dollars(net)
        if debit>gross: raise sk.Problem('Refund debit exceeds its gross amount.')
    contribution=sk.row(db,'SELECT amount FROM sk_ledger WHERE reference=?',(state['capture_id'],))
    if not contribution: raise sk.Problem('Recover the original contribution before its refund.',503)
    deducted=db.execute('SELECT COALESCE(SUM(principal),0) FROM sk_payment_refunds WHERE order_id=?',(order['id'],)).fetchone()[0]
    principal=min(max(0,contribution['amount']-deducted),debit)
    entry(db,order,'refund',principal,'REFUND-'+refund_id)
    entry(db,order,'refund_cost',debit-principal,'REFUND-COST-'+refund_id)
    entry(db,order,'refund_gross',gross,'REFUND-GROSS-'+refund_id)
    db.execute('INSERT INTO sk_payment_refunds VALUES(?,?,?,?,?,?)',(refund_id,order['id'],gross,debit,principal,core.now()))
    status='refunded' if prior+gross==order['amount'] else 'partially_refunded'
    db.execute('UPDATE sk_payment_state SET status=?,updated=? WHERE order_id=?',(status,core.now(),order['id']))
    invalidate(db,order,actor,'Reconciled sandbox refund '+refund_id)
    goal_status(db,order)

def reconcile_order(db,order,actor,refund_id=None,reversed_event=False):
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    identifier(order['id'])
    state=payment_state(db,order)
    token=core.paypal('/v1/oauth2/token')['access_token']
    result=core.paypal('/v2/checkout/orders/'+order['id'],token=token,method='GET')
    if result.get('id')!=order['id']: raise sk.Problem('Provider returned a different order.')
    units=result.get('purchase_units',[])
    if len(units)!=1: raise sk.Problem('This integration expects one contribution per order.')
    unit=units[0]
    if unit.get('payee',{}).get('email_address','').lower()!=state['recipient']:
        raise sk.Problem('Payment recipient does not match this order.')
    if dollars(unit.get('amount'))!=order['amount']: raise sk.Problem('Order amount changed.')
    captures=unit.get('payments',{}).get('captures',[])
    if not captures:
        if not order['captured']:
            local={'APPROVED':'approved','VOIDED':'failed','CREATED':'created','PAYER_ACTION_REQUIRED':'created'}.get(result.get('status'),'pending')
            db.execute('UPDATE sk_payment_state SET status=?,updated=? WHERE order_id=?',(local,core.now(),order['id']))
        return {'ok':False,'status':payment_state(db,order)['status'],'credited':bool(order['captured'])}
    if len(captures)!=1: raise sk.Problem('Multiple captures need manual review.')
    capture=captures[0]
    if not capture.get('seller_receivable_breakdown',{}).get('paypal_fee'):
        capture=core.paypal('/v2/payments/captures/'+identifier(capture.get('id')),token=token,method='GET')
    result_local=record_capture(db,order,unit,capture,actor)
    if not result_local['credited']: return result_local
    refunds={identifier(r['id']) for r in unit.get('payments',{}).get('refunds',[]) if r.get('status')=='COMPLETED'}
    if refund_id: refunds.add(identifier(refund_id))
    for ref in sorted(refunds):
        if not sk.row(db,'SELECT id FROM sk_payment_refunds WHERE id=?',(ref,)):
            detail=core.paypal('/v2/payments/refunds/'+ref,token=token,method='GET')
            if detail.get('id')!=ref: raise sk.Problem('Provider returned a different refund.')
            refund(db,order,detail,actor)
    state=payment_state(db,order)
    if reversed_event or capture.get('status')=='REVERSED':
        contribution=sk.row(db,'SELECT amount FROM sk_ledger WHERE reference=?',(state['capture_id'],))
        refunds_principal=db.execute('SELECT COALESCE(SUM(principal),0) FROM sk_payment_refunds WHERE order_id=?',(order['id'],)).fetchone()[0]
        reference='REVERSAL-'+state['capture_id']
        if not sk.row(db,'SELECT id FROM sk_ledger WHERE reference=?',(reference,)):
            entry(db,order,'reversal',max(0,contribution['amount']-refunds_principal),reference)
            invalidate(db,order,actor,'Payment reversed; officer reconciliation required')
        db.execute("UPDATE sk_payment_state SET status='reversed',needs_review=1,review_reason='reversed',updated=? WHERE order_id=?",(core.now(),order['id']))
    elif capture.get('status') in ('REFUNDED','PARTIALLY_REFUNDED') and not refunds:
        db.execute("UPDATE sk_payment_state SET status='review',needs_review=1,review_reason='missing_refund' WHERE order_id=?",(order['id'],))
    elif refunds and state.get('review_reason')=='missing_refund':
        db.execute('UPDATE sk_payment_state SET needs_review=0,review_reason=NULL WHERE order_id=?',(order['id'],))
    state=payment_state(db,order)
    return {'ok':not bool(state['needs_review']),'status':state['status'],'credited':True,'needsReview':bool(state['needs_review'])}

def webhook(headers,event):
    if core.MODE!='sandbox': raise sk.Problem('Sandbox webhooks are disabled in demo mode.',503)
    webhook_id=core.os.environ.get('PAYPAL_WEBHOOK_ID','')
    if not webhook_id: raise sk.Problem('Webhook verification is not configured.',503)
    headers={k.lower():v for k,v in headers.items()}
    mapping={'auth_algo':'paypal-auth-algo','cert_url':'paypal-cert-url','transmission_id':'paypal-transmission-id',
        'transmission_sig':'paypal-transmission-sig','transmission_time':'paypal-transmission-time'}
    if any(not headers.get(v) for v in mapping.values()): raise sk.Problem('Missing webhook signature headers.',400)
    cert=urlparse(headers['paypal-cert-url'])
    if cert.scheme!='https' or cert.hostname not in ('api.paypal.com','api.sandbox.paypal.com','api-m.paypal.com','api-m.sandbox.paypal.com'):
        raise sk.Problem('Unrecognized PayPal certificate URL.',400)
    token=core.paypal('/v1/oauth2/token')['access_token']
    verification=core.paypal('/v1/notifications/verify-webhook-signature',{
        **{key:headers[value] for key,value in mapping.items()},'webhook_id':webhook_id,'webhook_event':event},token)
    if verification.get('verification_status')!='SUCCESS': raise sk.Problem('Webhook signature was not verified.',401)
    event_id=identifier(event.get('id')); kind=event.get('event_type',''); resource=event.get('resource',{})
    if kind.startswith(('PAYMENT.PAYOUTSBATCH.','PAYMENT.PAYOUTS-ITEM.')):
        # Verified notifications trigger a fresh read from PayPal, never trust event amounts.
        batch_id=resource.get('batch_header',{}).get('payout_batch_id') or resource.get('payout_batch_id')
        with core.connect() as db:
            if sk.row(db,'SELECT id FROM sk_webhook_events WHERE id=?',(event_id,)): return {'ok':True,'duplicate':True}
            batch=sk.row(db,'SELECT cycle_id FROM sk_payout_batches WHERE batch_id=?',(batch_id,))
        status='ignored'
        if batch:
            from payouts import reconcile
            reconcile(batch['cycle_id'],batch_id,token)
            status='processed'
        with core.connect() as db:
            db.execute('INSERT OR IGNORE INTO sk_webhook_events VALUES(?,?,?,?)',(event_id,kind,status,core.now()))
        return {'ok':True,'status':status}
    accepted={'PAYMENT.CAPTURE.COMPLETED','PAYMENT.CAPTURE.PENDING','PAYMENT.CAPTURE.DENIED',
        'PAYMENT.CAPTURE.REFUNDED','PAYMENT.CAPTURE.REVERSED','CHECKOUT.ORDER.APPROVED'}
    with core.connect() as db:
        # Serialize event application with capture callbacks and other event deliveries.
        db.execute('BEGIN IMMEDIATE')
        if sk.row(db,'SELECT id FROM sk_webhook_events WHERE id=?',(event_id,)): return {'ok':True,'duplicate':True}
        status='ignored'
        if kind in accepted:
            refund_id=resource.get('id') if kind=='PAYMENT.CAPTURE.REFUNDED' and event.get('resource_type')!='capture' else None
            related=resource.get('supplementary_data',{}).get('related_ids',{})
            order_id=resource.get('id') if kind=='CHECKOUT.ORDER.APPROVED' else related.get('order_id')
            if not order_id:
                cap_id=capture_link(resource) if refund_id else identifier(resource.get('id'))
                capture=core.paypal('/v2/payments/captures/'+cap_id,token=token,method='GET')
                order_id=capture.get('supplementary_data',{}).get('related_ids',{}).get('order_id')
            order=sk.row(db,'SELECT * FROM sk_orders WHERE id=?',(order_id,))
            if order:
                reconcile_order(db,order,'PayPal verified event',refund_id,kind=='PAYMENT.CAPTURE.REVERSED')
                status='processed'
        db.execute('INSERT INTO sk_webhook_events VALUES(?,?,?,?)',(event_id,kind,status,core.now()))
        return {'ok':True,'status':status}
