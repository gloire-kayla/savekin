"""Member discussions, notifications and explicitly manual treasury handovers."""
import json
import os
import time
import savekin as sk


def active_handover(db,gid):
    return sk.row(db,"SELECT * FROM sk_treasury_handovers WHERE group_id=? AND status<>'complete' ORDER BY rowid DESC LIMIT 1",(gid,))


def receiving(db,group):
    account=sk.row(db,'SELECT * FROM sk_receiving_accounts WHERE group_id=? AND user_id=?',(group['id'],group['treasurer']))
    configured=os.environ.get('PAYPAL_TREASURER_EMAIL','').strip().lower()
    # Existing installations retain their configured treasury until it is explicitly changed.
    legacy=sk.row(db,'SELECT email FROM sk_users WHERE id=?',(group['treasurer'],))
    address=account['email'] if account else legacy['email'] if legacy else None
    ready=bool(address and address==configured and all(os.environ.get(k) for k in ('PAYPAL_CLIENT_ID','PAYPAL_CLIENT_SECRET')))
    return {'email':address,'declared':bool(account and address),'status':'sandbox_configured' if ready else 'setup_required',
        'ready':ready,'verification':'Sandbox configuration only; saving an email does not verify PayPal account ownership.'}


def unresolved(db,gid):
    return bool(sk.row(db,"SELECT o.id FROM sk_orders o LEFT JOIN sk_payment_state s ON s.order_id=o.id WHERE o.group_id=? AND (s.status IS NULL OR s.status NOT IN ('completed','partially_refunded','refunded','reversed','declined','failed','voided','cancelled') OR s.needs_review=1) LIMIT 1",(gid,)) or
        sk.row(db,"SELECT cycle_id FROM sk_payout_batches WHERE group_id=? AND status<>'complete' LIMIT 1",(gid,)))


def start_handover(db,group,new_user,proposal_id):
    if active_handover(db,group['id']): raise sk.Problem('Finish the existing treasurer handover first.')
    db.execute('INSERT INTO sk_treasury_handovers(id,group_id,proposal_id,outgoing,incoming,status,created) VALUES(?,?,?,?,?,?,?)',
        (sk.uid(),group['id'],proposal_id,group['treasurer'],new_user,'setup',sk.core.now()))


def treasury_snapshot(db,group):
    handover=active_handover(db,group['id']) or sk.row(db,'SELECT * FROM sk_treasury_handovers WHERE group_id=? ORDER BY rowid DESC LIMIT 1',(group['id'],))
    if handover:
        handover['statement']=json.loads(handover['statement']) if handover['statement'] else None
    history=sk.rows(db,'SELECT e.actor,e.action,e.details,e.created FROM sk_handover_history e JOIN sk_treasury_handovers h ON h.id=e.handover_id WHERE h.group_id=? ORDER BY e.rowid DESC LIMIT 50',(group['id'],))
    for event in history: event['details']=json.loads(event['details'])
    incoming=sk.row(db,'SELECT email FROM sk_receiving_accounts WHERE group_id=? AND user_id=?',(group['id'],handover['incoming'])) if handover else None
    return {'receiving':receiving(db,group),'incomingReceiving':incoming,'handover':handover,'history':history}


def handle_treasury(db,path,body,actor,group):
    gid=group['id']; h=active_handover(db,gid)
    if path=='/api/treasury/account':
        target=h['incoming'] if h else group['treasurer']
        if actor!=target: raise sk.Problem('Only the current or approved incoming treasurer can set this receiving account.',403)
        if h and h['status']!='setup': raise sk.Problem('The receiving account is frozen in the handover statement.')
        if not h and sk.current(db,gid)['status'] not in ('open','goal_reached'):
            raise sk.Problem('Finish settlement before changing treasury settings.')
        from account_features import email
        address=email(body.get('email',''))
        if body.get('confirm') is not True: raise sk.Problem('Confirm this is a sandbox business account you control.')
        if not h and (sk.snapshot(db,gid)['pool'] or unresolved(db,gid)):
            previous=receiving(db,group)['email']
            if address!=previous: raise sk.Problem('Funds or payments exist. Use an approved treasurer handover to change the receiving account.')
        db.execute('INSERT INTO sk_receiving_accounts VALUES(?,?,?,?) ON CONFLICT(group_id,user_id) DO UPDATE SET email=excluded.email,updated=excluded.updated',(gid,actor,address,sk.core.now()))
        sk.audit(db,gid,actor,'Declared sandbox treasury receiving account')
        return {'ok':True}
    if not h: raise sk.Problem('No pending treasurer handover.',404)
    if path=='/api/treasury/statement':
        if actor!=h['outgoing']: raise sk.Problem('The outgoing treasurer prepares the handover statement.',403)
        if h['status'] not in ('setup','review'): raise sk.Problem('This statement is frozen after transfer is declared.')
        if unresolved(db,gid): raise sk.Problem('Resolve every outstanding payment and payout before preparing the statement. Check created orders in Ledger too.')
        account=sk.row(db,'SELECT email FROM sk_receiving_accounts WHERE group_id=? AND user_id=?',(gid,h['incoming']))
        if not account: raise sk.Problem('The incoming treasurer must first declare their receiving account.')
        amount=sk.money(body.get('amount'),group['currency'],True)
        pool=sk.snapshot(db,gid)['pool']
        if amount!=pool: raise sk.Problem('The available group funds must equal the recorded pool. Resolve discrepancies in the ledger before handover.')
        fees=sk.money(body.get('fees','0'),group['currency'],True)
        statement={'amount':amount,'fees':fees,'feePayer':sk.clean(body.get('feePayer',''),160),
            'note':sk.clean(body.get('note',''),1000),'recipient':account['email'],'pool':pool,
            'outgoingAccount':receiving(db,group)['email'],'verification':'Manual handover; no PayPal transfer is initiated or verified by SaveKin.'}
        db.execute("UPDATE sk_treasury_handovers SET statement=?,status='review',reference=NULL,received=0,president_confirmed=0 WHERE id=?",(json.dumps(statement),h['id']))
        db.execute('DELETE FROM sk_handover_votes WHERE handover_id=?',(h['id'],))
    elif path=='/api/treasury/statement-vote':
        if h['status']!='review': raise sk.Problem('The statement is not awaiting member approval.')
        member=sk.row(db,"SELECT id FROM sk_members WHERE group_id=? AND user_id=? AND status='active'",(gid,actor))
        if not member: raise sk.Problem('Only active members vote on handover fees and terms.',403)
        if not isinstance(body.get('approve'),bool): raise sk.Problem('Choose approve or reject.')
        db.execute('INSERT INTO sk_handover_votes VALUES(?,?,?)',(h['id'],actor,int(body['approve'])))
    elif path=='/api/treasury/transfer':
        if actor!=h['outgoing'] or h['status']!='review': raise sk.Problem('Only the outgoing treasurer can declare the transfer after review.',403)
        voters=sk.rows(db,"SELECT user_id FROM sk_members WHERE group_id=? AND status='active'",(gid,))
        approvals=sk.rows(db,'SELECT user_id FROM sk_handover_votes WHERE handover_id=? AND approve=1',(h['id'],))
        approved={r['user_id'] for r in approvals}
        if len(approved)<(2*len(voters)+2)//3 or not {h['incoming'],h['outgoing'],group['president']}<=approved:
            raise sk.Problem('At least two-thirds of active members, including both treasurers and the president, must approve the statement and fees.')
        statement=json.loads(h['statement'])
        if unresolved(db,gid) or sk.snapshot(db,gid)['pool']!=statement['pool']: raise sk.Problem('Payments or ledger totals changed. Prepare a new handover statement.')
        if body.get('confirm') is not True: raise sk.Problem('Confirm the transfer was made outside SaveKin; this does not initiate a payment.')
        db.execute("UPDATE sk_treasury_handovers SET reference=?,status='transferred' WHERE id=?",(sk.clean(body.get('reference',''),160),h['id']))
    elif path=='/api/treasury/confirm':
        if h['status']!='transferred': raise sk.Problem('The outgoing treasurer must first declare the transfer.')
        if actor not in (h['incoming'],group['president']): raise sk.Problem('Only the incoming treasurer and president confirm receipt.',403)
        if body.get('confirm') is not True: raise sk.Problem('Confirm you independently reviewed the amount and transfer evidence.')
        statement=json.loads(h['statement'])
        if unresolved(db,gid) or sk.snapshot(db,gid)['pool']!=statement['pool']: raise sk.Problem('The ledger or payments changed. Handover needs reconciliation.')
        column='received' if actor==h['incoming'] else 'president_confirmed'
        db.execute('UPDATE sk_treasury_handovers SET '+column+'=1 WHERE id=?',(h['id'],))
        latest=sk.row(db,'SELECT * FROM sk_treasury_handovers WHERE id=?',(h['id'],))
        if latest['received'] and latest['president_confirmed']:
            new_group={**group,'treasurer':h['incoming']}
            if sk.core.MODE=='sandbox' and not receiving(db,new_group)['ready']:
                # Keep the confirmations and funds record, but do not activate an unsupported destination.
                db.execute('INSERT INTO sk_handover_history VALUES(?,?,?,?,?,?)',(sk.uid(),h['id'],actor,'confirm-awaiting-configuration',json.dumps({'statement':statement,'reference':h['reference']}),sk.core.now()))
                return {'ok':True,'message':'Receipt confirmations saved. Activation awaits sandbox server configuration for the incoming receiving account.'}
            db.execute('UPDATE sk_groups SET treasurer=? WHERE id=?',(h['incoming'],gid))
            db.execute("UPDATE sk_treasury_handovers SET status='complete',completed=? WHERE id=?",(sk.core.now(),h['id']))
    else: raise sk.Problem('Treasury operation not found.',404)
    latest=sk.row(db,'SELECT statement,reference,status FROM sk_treasury_handovers WHERE id=?',(h['id'],))
    latest['statement']=json.loads(latest['statement']) if latest['statement'] else None
    db.execute('INSERT INTO sk_handover_history VALUES(?,?,?,?,?,?)',(sk.uid(),h['id'],actor,path.rsplit('/',1)[-1],json.dumps(latest),sk.core.now()))
    sk.audit(db,gid,actor,'Treasurer handover: '+path.rsplit('/',1)[-1])
    return {'ok':True}


def discussion(db,body,actor,group,member):
    if member['status'] not in ('active','waiting','exit_pending','exit_approved'): raise sk.Problem('Only current group members can access discussions.',403)
    gid=group['id']; action=body.get('action','list')
    if action=='send':
        content=sk.clean(body.get('message',''),2000); key=sk.clean(body.get('clientId',''),100)
        existing=sk.row(db,'SELECT id,group_id FROM sk_discussions WHERE user_id=? AND client_id=?',(actor,key))
        if existing:
            if existing['group_id']!=gid: raise sk.Problem('Message reference belongs to another group.')
            return {'ok':True,'id':existing['id']}
        recent=db.execute('SELECT COUNT(*) FROM sk_discussions WHERE user_id=? AND sent_at>?',(actor,time.time()-10)).fetchone()[0]
        if recent>=5: raise sk.Problem('Please wait a moment before sending more messages.',429)
        name=sk.row(db,'SELECT name FROM sk_users WHERE id=?',(actor,))['name']
        cursor=db.execute('INSERT INTO sk_discussions(group_id,user_id,sender_name,content,client_id,created,sent_at) VALUES(?,?,?,?,?,?,?)',(gid,actor,name,content,key,sk.core.now(),time.time()))
        return {'ok':True,'id':cursor.lastrowid}
    before=sk.integer(body['before'],1,2**53) if body.get('before') else 2**53
    messages=sk.rows(db,'SELECT id,user_id,sender_name,content,created FROM sk_discussions WHERE group_id=? AND id<? ORDER BY id DESC LIMIT 51',(gid,before))
    more=len(messages)>50; messages=list(reversed(messages[:50]))
    if action=='read':
        through=sk.integer(body.get('through',0),0,2**53)
        maximum=db.execute('SELECT COALESCE(MAX(id),0) FROM sk_discussions WHERE group_id=?',(gid,)).fetchone()[0]
        db.execute('INSERT INTO sk_discussion_reads VALUES(?,?,?) ON CONFLICT(group_id,user_id) DO UPDATE SET last_id=MAX(last_id,excluded.last_id)',(gid,actor,min(through,maximum)))
    elif action!='list': raise sk.Problem('Unknown discussion action.')
    return {'messages':messages,'hasMore':more}


def notifications(db,actor):
    items=[]
    groups=sk.rows(db,"SELECT g.* FROM sk_groups g JOIN sk_members m ON m.group_id=g.id WHERE m.user_id=? AND m.status IN ('active','waiting','exit_pending','exit_approved')",(actor,))
    for group in groups:
        gid=group['id']; cycle=sk.current(db,gid)
        member=sk.row(db,'SELECT * FROM sk_members WHERE group_id=? AND user_id=?',(gid,actor))
        due=sk.amounts(db,member,cycle,json.loads(group['rules']))['arrears']
        if due and cycle['status'] in ('open','goal_reached'):
            items.append({'id':'due:'+cycle['id']+':'+str(sk.period(cycle))+':'+str(due),'groupId':gid,'page':'overview','text':group['name']+': your contribution is due.'})
        read=sk.row(db,'SELECT last_id FROM sk_discussion_reads WHERE group_id=? AND user_id=?',(gid,actor))
        count=db.execute('SELECT COUNT(*) FROM sk_discussions WHERE group_id=? AND user_id<>? AND id>?',(gid,actor,read['last_id'] if read else 0)).fetchone()[0]
        if count: items.append({'id':'discussion:'+gid,'groupId':gid,'page':'discussions','text':group['name']+f': {count} unread discussion messages.','unread':True})
        for p in sk.rows(db,"SELECT id,kind FROM sk_proposals WHERE group_id=? AND status='pending'",(gid,)):
            items.append({'id':'proposal:'+p['id'],'groupId':gid,'page':'decisions','text':group['name']+': pending '+p['kind']+' proposal.'})
        h=active_handover(db,gid)
        if h: items.append({'id':'handover:'+h['id']+':'+h['status'],'groupId':gid,'page':'treasury','text':group['name']+': treasurer handover '+h['status']+'.'})
        for a in sk.rows(db,'SELECT id,action FROM sk_audit WHERE group_id=? ORDER BY rowid DESC LIMIT 8',(gid,)):
            if a['action'].startswith('Treasurer handover:') or a['action'].startswith('Voted on treasurer'):
                items.append({'id':'audit:'+a['id'],'groupId':gid,'page':'treasury','text':group['name']+': '+a['action']})
    read={r['item_id'] for r in sk.rows(db,'SELECT item_id FROM sk_notification_reads WHERE user_id=?',(actor,))}
    for item in items:
        if 'unread' not in item: item['unread']=item['id'] not in read
    return items
