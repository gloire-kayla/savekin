"""Sandbox cycle payouts, with a durable request journal and frozen recipients.

No live endpoint exists. Failed/uncertain batches are never replaced automatically.
Provider fees are paid separately by the test treasurer, not silently deducted.
"""
import json
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
import server as core
import savekin as sk


def provider_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value):
        raise sk.Problem('Invalid payout reference from provider.')
    return value


def operate(path,body,token):
    if core.MODE!='sandbox': raise sk.Problem('PayPal payouts are sandbox-only.')
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        actor=sk.authenticate(db,token)['id']
        group,_=sk.access(db,body.get('groupId'),actor)
        cycle=sk.current(db,group['id'])
        if actor!=group['treasurer']: raise sk.Problem('Only the elected treasurer sends or checks payouts.',403)
        from group_features import receiving,active_handover
        if active_handover(db,group['id']) and path.endswith('/send'):
            raise sk.Problem('Distribution is paused during treasurer handover.')
        account=receiving(db,group); recipient=account['email']
        if not account['ready']: raise sk.Problem('Treasury needs its configured sandbox receiving account.')
        if group['currency']!='USD': raise sk.Problem('Sandbox payouts support USD only.')
        batch=sk.row(db,'SELECT * FROM sk_payout_batches WHERE cycle_id=?',(cycle['id'],))
        if not batch:
            if path.endswith('/check'): raise sk.Problem('No payout batch has been submitted.')
            if body.get('confirm') is not True: raise sk.Problem('Confirm the sandbox distribution and sender-paid fees.')
            if cycle['status']!='approved' or not cycle['settlement']:
                raise sk.Problem('Both officers must approve settlement first.')
            snap=sk.snapshot(db,group['id'])
            if any(o['needs_review'] or o['status'] in ('pending','approved') for o in snap['paymentOrders']):
                raise sk.Problem('Resolve payment reviews before sending payouts.')
            statement=json.loads(cycle['settlement']); allocations=statement['allocations']
            if not allocations or len(allocations)>1000: raise sk.Problem('Sandbox supports 1–1000 recipients.')
            if sum(a['amount'] for a in allocations)+statement['carried']!=statement['pool'] or statement['pool']!=snap['pool']:
                raise sk.Problem('Settlement totals changed. Do not send this distribution.')
            sender='SK-'+cycle['id']
            items=[]
            for a in allocations:
                email=a.get('receiver','')
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or a['amount']<=0:
                    raise sk.Problem('Approved settlement needs valid sandbox destinations. Propose a new settlement.')
                # Funds assigned to the funding account remain there; no self-transfer.
                retained=email==recipient
                db.execute('INSERT INTO sk_payout_items VALUES(?,?,?,?,?,?)',
                    (cycle['id'],a['memberId'],email,a['amount'],'retained' if retained else 'queued',None))
                if not retained:
                    items.append({'recipient_type':'EMAIL','receiver':email,'sender_item_id':a['memberId'],
                        'amount':{'value':f"{a['amount']//100}.{a['amount']%100:02d}",'currency':'USD'},
                        'note':'SaveKin sandbox savings-cycle distribution'})
            payload={'sender_batch_header':{'sender_batch_id':sender,'email_subject':'SaveKin sandbox distribution'},'items':items}
            journal={'request':payload,'clientFingerprint':hashlib.sha256(core.os.environ.get('PAYPAL_CLIENT_ID','').encode()).hexdigest(),
                'treasury':recipient}
            db.execute('INSERT INTO sk_payout_batches VALUES(?,?,?,?,?,?,?,?)',
                (cycle['id'],group['id'],sender,None,'prepared',json.dumps(journal),core.now(),core.now()))
            db.execute("UPDATE sk_cycles SET status='paying' WHERE id=?",(cycle['id'],))
            sk.audit(db,group['id'],actor,'Prepared sandbox distribution; provider fees borne separately by treasurer')
            batch=sk.row(db,'SELECT * FROM sk_payout_batches WHERE cycle_id=?',(cycle['id'],))
        if cycle['status']=='reconciliation_required': raise sk.Problem('Cycle requires reconciliation. No further payout request will be sent.')
        if batch['status']=='complete' and path.endswith('/send'): return {'status':'complete'}
        journal=json.loads(batch['payload'])
        if journal['clientFingerprint']!=hashlib.sha256(core.os.environ.get('PAYPAL_CLIENT_ID','').encode()).hexdigest() or journal['treasury']!=recipient:
            raise sk.Problem('This batch belongs to a different sandbox app configuration. Restore the original configuration to reconcile it.')
        if not batch['batch_id'] and batch['status']=='submitting':
            if (datetime.now(timezone.utc)-datetime.fromisoformat(batch['updated'])).total_seconds()<90:
                raise sk.Problem('A payout request is in progress. Wait before checking again.',409)
        if not batch['batch_id']:
            if path.endswith('/check'): raise sk.Problem('Outcome unknown. Use Resume same batch; it reuses the saved request.')
            if body.get('confirm') is not True: raise sk.Problem('Confirm resuming the saved sandbox batch.')
            age=datetime.now(timezone.utc)-datetime.fromisoformat(batch['created'])
            if age.days>=29: raise sk.Problem('Batch is too old to safely retry. Review it in PayPal; no new batch was created.')
            db.execute("UPDATE sk_payout_batches SET status='submitting',updated=? WHERE cycle_id=?",(core.now(),cycle['id']))
        # Commit the immutable request BEFORE contacting PayPal. A timeout cannot lose it.
    payload=json.loads(batch['payload'])['request']
    try:
        access_token=core.paypal('/v1/oauth2/token')['access_token']
        batch_id=batch['batch_id']
        if not payload['items']:
            return finalize_retained(cycle['id'])
        if not batch_id:
            try:
                result=core.paypal('/v1/payments/payouts',payload,access_token,batch['sender_id'])
                header=result.get('batch_header',{})
                if header.get('sender_batch_header',{}).get('sender_batch_id')!=batch['sender_id']:
                    raise sk.Problem('Provider batch identity was not confirmed.')
                batch_id=provider_id(header.get('payout_batch_id'))
            except core.urllib.error.HTTPError as exc:
                # Duplicate requests may return the original batch link. Never follow arbitrary URLs.
                try: failure=json.loads(exc.read(65536))
                except (ValueError,TypeError): raise exc
                finally: exc.close()
                links=list(failure.get('links',[]))
                for detail in failure.get('details',[]): links.extend(detail.get('links',[]))
                for link in links:
                    url=urlparse(link.get('href',''))
                    if url.scheme=='https' and url.hostname in ('api-m.sandbox.paypal.com','api.sandbox.paypal.com') and re.fullmatch(r'/v1/payments/payouts/[A-Za-z0-9_-]+',url.path):
                        batch_id=provider_id(url.path.rsplit('/',1)[-1]); break
                if not batch_id: raise exc
            with core.connect() as db:
                db.execute("UPDATE sk_payout_batches SET batch_id=?,status='pending',updated=? WHERE cycle_id=?",(batch_id,core.now(),cycle['id']))
        return reconcile(cycle['id'],batch_id,access_token)
    except Exception:
        with core.connect() as db:
            db.execute("UPDATE sk_payout_batches SET status=CASE WHEN batch_id IS NULL THEN 'unknown' ELSE status END,updated=? WHERE cycle_id=?",(core.now(),cycle['id']))
        raise


def finalize_retained(cid):
    with core.connect() as db:
        db.execute("UPDATE sk_payout_batches SET status='complete',updated=? WHERE cycle_id=?",(core.now(),cid))
        db.execute("UPDATE sk_cycles SET status='distributed' WHERE id=? AND status='paying'",(cid,))
    return {'status':'complete'}


def reconcile(cid,batch_id,token):
    result=core.paypal('/v1/payments/payouts/'+provider_id(batch_id)+'?page_size=1000&page=1',token=token,method='GET')
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        batch=sk.row(db,'SELECT * FROM sk_payout_batches WHERE cycle_id=?',(cid,))
        header=result.get('batch_header',{})
        if header.get('payout_batch_id')!=batch_id or header.get('sender_batch_header',{}).get('sender_batch_id')!=batch['sender_id']:
            raise sk.Problem('Provider returned a different payout batch.')
        expected={i['sender_item_id']:i for i in json.loads(batch['payload'])['request']['items']}
        seen=set()
        for item in result.get('items',[]):
            data=item.get('payout_item',{}); key=data.get('sender_item_id'); original=expected.get(key)
            if key in seen or not original or data.get('receiver','').lower()!=original['receiver'] or data.get('amount',{}).get('currency')!='USD' or sk.money(data.get('amount',{}).get('value'))!=sk.money(original['amount']['value']):
                raise sk.Problem('Payout item does not match the frozen settlement.')
            seen.add(key)
            status=item.get('transaction_status','PENDING')
            if status not in ('SUCCESS','PENDING','UNCLAIMED','FAILED','DENIED','BLOCKED','RETURNED','REFUNDED','ONHOLD','CANCELED'):
                status='REVIEW'
            reference=provider_id(item.get('payout_item_id'))
            db.execute('UPDATE sk_payout_items SET status=?,reference=? WHERE cycle_id=? AND member_id=?',(status,reference,cid,key))
        complete=len(seen)==len(expected) and all(i['status'] in ('SUCCESS','retained') for i in sk.rows(db,'SELECT status FROM sk_payout_items WHERE cycle_id=?',(cid,)))
        state='complete' if complete else 'review' if header.get('batch_status') in ('DENIED','CANCELED') or any(i['status'] in ('FAILED','DENIED','BLOCKED','RETURNED','REFUNDED','CANCELED','REVIEW') for i in sk.rows(db,'SELECT status FROM sk_payout_items WHERE cycle_id=?',(cid,))) else 'pending'
        db.execute('UPDATE sk_payout_batches SET status=?,updated=? WHERE cycle_id=?',(state,core.now(),cid))
        cycle=sk.row(db,'SELECT status FROM sk_cycles WHERE id=?',(cid,))
        if complete and cycle['status']=='paying':
            db.execute("UPDATE sk_cycles SET status='distributed' WHERE id=?",(cid,))
            sk.audit(db,batch['group_id'],'PayPal reconciliation','All outbound sandbox payout items confirmed; treasury allocation retained')
        elif not complete and cycle['status']=='distributed':
            db.execute("UPDATE sk_cycles SET status='reconciliation_required' WHERE id=?",(cid,))
        return {'status':state}
