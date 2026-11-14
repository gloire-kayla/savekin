"""SaveKin domain and authenticated API. Local development, demo/sandbox only."""
import base64
import hashlib
import hmac
import json
import math
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs
import server as core

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sk_users(id TEXT PRIMARY KEY,name TEXT,email TEXT UNIQUE,password TEXT);
CREATE TABLE IF NOT EXISTS sk_sessions(token TEXT PRIMARY KEY,user_id TEXT,expires INTEGER);
CREATE TABLE IF NOT EXISTS sk_groups(id TEXT PRIMARY KEY,name TEXT,president TEXT,treasurer TEXT,
 currency TEXT,rules TEXT,invite TEXT UNIQUE,created TEXT);
CREATE TABLE IF NOT EXISTS sk_cycles(id TEXT PRIMARY KEY,group_id TEXT,number INTEGER,start TEXT,
 end TEXT,status TEXT,settlement TEXT,UNIQUE(group_id,number));
CREATE TABLE IF NOT EXISTS sk_members(id TEXT PRIMARY KEY,group_id TEXT,user_id TEXT,status TEXT,
 shares INTEGER,next_shares INTEGER,accepted TEXT,UNIQUE(group_id,user_id));
CREATE TABLE IF NOT EXISTS sk_ledger(id TEXT PRIMARY KEY,group_id TEXT,cycle_id TEXT,member_id TEXT,
 kind TEXT,amount INTEGER,reference TEXT UNIQUE,created TEXT);
CREATE TABLE IF NOT EXISTS sk_proposals(id TEXT PRIMARY KEY,group_id TEXT,kind TEXT,payload TEXT,
 status TEXT,created TEXT,cycle_id TEXT,electorate TEXT);
CREATE TABLE IF NOT EXISTS sk_votes(proposal_id TEXT,user_id TEXT,approve INTEGER,PRIMARY KEY(proposal_id,user_id));
CREATE TABLE IF NOT EXISTS sk_approvals(proposal_id TEXT,user_id TEXT,PRIMARY KEY(proposal_id,user_id));
CREATE TABLE IF NOT EXISTS sk_audit(id TEXT PRIMARY KEY,group_id TEXT,actor TEXT,action TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS sk_orders(id TEXT PRIMARY KEY,group_id TEXT,cycle_id TEXT,member_id TEXT,
 user_id TEXT,amount INTEGER,captured INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sk_payment_state(order_id TEXT PRIMARY KEY,recipient TEXT,capture_id TEXT UNIQUE,
 status TEXT NOT NULL DEFAULT 'created',needs_review INTEGER NOT NULL DEFAULT 0,updated TEXT,review_reason TEXT);
CREATE TABLE IF NOT EXISTS sk_payment_refunds(id TEXT PRIMARY KEY,order_id TEXT,gross INTEGER,debit INTEGER,
 principal INTEGER,created TEXT);
CREATE TABLE IF NOT EXISTS sk_webhook_events(id TEXT PRIMARY KEY,type TEXT,status TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS sk_payout_accounts(user_id TEXT PRIMARY KEY,email TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sk_handoffs(code TEXT PRIMARY KEY,user_id TEXT,group_id TEXT,expires INTEGER);
CREATE TABLE IF NOT EXISTS sk_payment_quotes(id TEXT PRIMARY KEY,group_id TEXT,cycle_id TEXT,user_id TEXT,
 target INTEGER,gross INTEGER,fee INTEGER,expires INTEGER,order_id TEXT);
CREATE TABLE IF NOT EXISTS sk_treasury_evidence(proposal_id TEXT PRIMARY KEY,name TEXT,mime TEXT,data BLOB);
CREATE TABLE IF NOT EXISTS sk_assistant_chats(id TEXT PRIMARY KEY,user_id TEXT,group_id TEXT,title TEXT,created TEXT,updated TEXT);
CREATE TABLE IF NOT EXISTS sk_assistant_messages(id TEXT PRIMARY KEY,chat_id TEXT,role TEXT,content TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS sk_profiles(user_id TEXT PRIMARY KEY,photo TEXT,verified_email TEXT);
CREATE TABLE IF NOT EXISTS sk_email_codes(user_id TEXT,kind TEXT,email TEXT,code TEXT,expires INTEGER,attempts INTEGER,created INTEGER,password_version TEXT,delivery TEXT,PRIMARY KEY(user_id,kind));
CREATE TABLE IF NOT EXISTS sk_discussions(id INTEGER PRIMARY KEY AUTOINCREMENT,group_id TEXT,user_id TEXT,sender_name TEXT,content TEXT,client_id TEXT,created TEXT,sent_at REAL,UNIQUE(user_id,client_id));
CREATE INDEX IF NOT EXISTS sk_discussion_group ON sk_discussions(group_id,id);
CREATE TABLE IF NOT EXISTS sk_discussion_reads(group_id TEXT,user_id TEXT,last_id INTEGER,PRIMARY KEY(group_id,user_id));
CREATE TABLE IF NOT EXISTS sk_notification_reads(user_id TEXT,item_id TEXT,PRIMARY KEY(user_id,item_id));
CREATE TABLE IF NOT EXISTS sk_receiving_accounts(group_id TEXT,user_id TEXT,email TEXT,updated TEXT,PRIMARY KEY(group_id,user_id));
CREATE TABLE IF NOT EXISTS sk_treasury_handovers(id TEXT PRIMARY KEY,group_id TEXT,proposal_id TEXT,outgoing TEXT,incoming TEXT,status TEXT,statement TEXT,reference TEXT,received INTEGER DEFAULT 0,president_confirmed INTEGER DEFAULT 0,created TEXT,completed TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS sk_handover_reference ON sk_treasury_handovers(group_id,reference) WHERE reference IS NOT NULL;
CREATE TABLE IF NOT EXISTS sk_handover_history(id TEXT PRIMARY KEY,handover_id TEXT,actor TEXT,action TEXT,details TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS sk_handover_votes(handover_id TEXT,user_id TEXT,approve INTEGER,PRIMARY KEY(handover_id,user_id));
CREATE TABLE IF NOT EXISTS sk_preferences(user_id TEXT PRIMARY KEY,last_group TEXT);
CREATE TABLE IF NOT EXISTS sk_ai_consents(user_id TEXT,provider TEXT,version TEXT,accepted TEXT,PRIMARY KEY(user_id,provider,version));
CREATE TABLE IF NOT EXISTS sk_payout_batches(cycle_id TEXT PRIMARY KEY,group_id TEXT,sender_id TEXT UNIQUE,
 batch_id TEXT,status TEXT,payload TEXT,created TEXT,updated TEXT);
CREATE TABLE IF NOT EXISTS sk_payout_items(cycle_id TEXT,member_id TEXT,receiver TEXT,amount INTEGER,
 status TEXT,reference TEXT,PRIMARY KEY(cycle_id,member_id));
'''
with core.connect() as db:
    db.executescript(SCHEMA)
    if 'review_reason' not in {r['name'] for r in db.execute('PRAGMA table_info(sk_payment_state)')}:
        db.execute('ALTER TABLE sk_payment_state ADD COLUMN review_reason TEXT')

class Problem(ValueError):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status

def uid(): return secrets.token_hex(12)
def row(db,sql,args=()):
    result=db.execute(sql,args).fetchone()
    return dict(result) if result else None
def rows(db,sql,args=()): return [dict(r) for r in db.execute(sql,args)]
def digest(token): return hashlib.sha256(token.encode()).hexdigest()
def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def integer(value,minimum=1,maximum=100000):
    try:
        if isinstance(value,bool) or str(int(value))!=str(value): raise ValueError()
        number=int(value)
    except (ValueError,TypeError): raise Problem('Enter a whole number.')
    if not minimum<=number<=maximum: raise Problem(f'Choose a number from {minimum} to {maximum}.')
    return number
def clean(value,maximum=100):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>maximum:
        raise Problem(f'Enter text between 1 and {maximum} characters.')
    return value.strip()
def money(value,currency='USD',zero=False):
    if zero and str(value) in ('0','0.0','0.00'): return 0
    cents=core.amount(value)
    if currency=='RWF' and cents%100: raise Problem('Use whole Rwandan francs.')
    return cents
def audit(db,gid,actor,action):
    db.execute('INSERT INTO sk_audit VALUES(?,?,?,?,?)',(uid(),gid,actor,action,core.now()))
def current(db,gid):
    return row(db,'SELECT * FROM sk_cycles WHERE group_id=? ORDER BY number DESC LIMIT 1',(gid,))
def period(cycle,today=None):
    today=today or date.today()
    start=date.fromisoformat(cycle['start']); end=date.fromisoformat(cycle['end'])
    today=min(today,end)
    return max(1,(today.year-start.year)*12+today.month-start.month+1)
def rules_from(body,currency):
    ending=body.get('ending','date')
    if ending not in ('date','goal','repeat'): raise Problem('Choose a date, goal or repeating cycle.')
    joining=body.get('joining','next_cycle')
    if joining not in ('next_cycle','catch_up'): raise Problem('Choose a valid joining policy.')
    return {'sharePrice':money(body.get('sharePrice'),currency),
      'goal':money(body.get('goal'),currency),'ending':ending,'joining':joining,
      'months':integer(body.get('months',12),1,120),
      'fine':money(body.get('fine',0),currency,True),
      'exitPenalty':money(body.get('exitPenalty',0),currency,True),
      'surplus':body.get('surplus','distribute') if body.get('surplus','distribute') in ('distribute','carry') else 'distribute',
      'voting':'one member one vote; approval requires at least 2/3 of eligible members voting yes'}
def amounts(db,member,cycle,rules):
    entries=rows(db,'SELECT kind,amount FROM sk_ledger WHERE member_id=? AND cycle_id=?',(member['id'],cycle['id']))
    paid=sum(e['amount'] for e in entries if e['kind'] in ('contribution','treasury_contribution'))-sum(e['amount'] for e in entries if e['kind'] in ('refund','reversal'))
    principal=paid-sum(e['amount'] for e in entries if e['kind']=='exit_principal')
    due=member['shares']*rules['sharePrice']*period(cycle) if member['status']=='active' else 0
    return {'paid':paid,'principal':principal,'due':due,'arrears':max(0,due-paid),'credit':max(0,paid-due)}
def snapshot(db,gid):
    group=row(db,'SELECT * FROM sk_groups WHERE id=?',(gid,))
    rules=json.loads(group['rules']); cycle=current(db,gid)
    people=rows(db,'SELECT m.*,u.name,u.email FROM sk_members m JOIN sk_users u ON u.id=m.user_id WHERE group_id=?',(gid,))
    entries=rows(db,'SELECT * FROM sk_ledger WHERE cycle_id=? ORDER BY created',(cycle['id'],))
    for member in people: member.update(amounts(db,member,cycle,rules))
    gross=sum(e['amount'] for e in entries if e['kind'] in ('contribution','treasury_contribution'))-sum(e['amount'] for e in entries if e['kind'] in ('refund','reversal'))
    penalties=sum(e['amount'] for e in entries if e['kind'] in ('fine','exit_penalty','carry'))
    out=sum(e['amount'] for e in entries if e['kind'] in ('expense','exit_principal','refund_cost'))
    pool=gross+penalties-out
    eligible=[m for m in people if m['status']=='active' and m['arrears']==0 and m['principal']>0]
    principal=sum(m['principal'] for m in eligible)
    total_principal=sum(m['principal'] for m in people if m['status']=='active')
    surplus=pool-total_principal
    allocations=[]
    # Integer largest-remainder allocation prevents losing or inventing cents.
    weights=sum(m['shares'] for m in eligible)
    split=max(0,surplus) if rules['surplus']=='distribute' else 0
    quantum=100 if group['currency']=='RWF' else 1
    units=split//quantum
    allocated={m['id']:(units*m['shares']//weights if weights else 0) for m in eligible}
    remainder=units-sum(allocated.values())
    if weights:
        rank=sorted(eligible,key=lambda m:(-(units*m['shares']%weights),m['id']))
        for member in rank[:remainder]: allocated[member['id']]+=1
    allocated={key:value*quantum for key,value in allocated.items()}
    for member in eligible:
        allocations.append({'memberId':member['id'],'name':member['name'],'shares':member['shares'],
            'principal':member['principal'],'surplus':allocated[member['id']],
            'amount':member['principal']+allocated[member['id']]})
    group['rules']=rules; group['cycle']=cycle; group['members']=people
    group['ledger']=entries; group['gross']=gross; group['pool']=pool; group['surplus']=surplus
    group['allocations']=allocations; group['carried']=max(0,surplus) if rules['surplus']=='carry' else 0
    group['period']=period(cycle)
    group['payoutBatch']=row(db,'SELECT cycle_id,batch_id,status,created,updated FROM sk_payout_batches WHERE cycle_id=?',(cycle['id'],))
    group['payoutItems']=rows(db,'SELECT member_id,receiver,amount,status,reference FROM sk_payout_items WHERE cycle_id=?',(cycle['id'],))
    group['paymentOrders']=rows(db,'SELECT o.*,s.status,s.needs_review,s.updated,q.target,q.fee AS estimated_fee FROM sk_orders o LEFT JOIN sk_payment_state s ON s.order_id=o.id LEFT JOIN sk_payment_quotes q ON q.order_id=o.id WHERE o.group_id=? ORDER BY o.rowid DESC',(gid,))
    unresolved=any(o['needs_review'] or o['cycle_id']==cycle['id'] and o['status'] in ('pending','approved') for o in group['paymentOrders'])
    unresolved=unresolved or bool(row(db,"SELECT id FROM sk_cycles WHERE group_id=? AND status='reconciliation_required'",(gid,)))
    unsettled_exits=any(m['status'] in ('exit_pending','exit_approved') for m in people)
    pending_governance=bool(row(db,"SELECT id FROM sk_proposals WHERE group_id=? AND status='pending' AND kind IN ('rules','president','treasurer','treasury')",(gid,)))
    group['canSettle']=bool(group['treasurer'] and eligible and not unresolved and not unsettled_exits and not pending_governance and not any(m['arrears'] for m in people if m['status']=='active')
        and surplus>=0 and cycle['status'] in ('open','goal_reached')
        and (gross>=rules['goal'] if rules['ending']=='goal' else date.today()>=date.fromisoformat(cycle['end'])))
    group['proposals']=rows(db,'SELECT * FROM sk_proposals WHERE group_id=? ORDER BY created DESC',(gid,))
    for proposal in group['proposals']:
        proposal['payload']=json.loads(proposal['payload']); proposal['electorate']=json.loads(proposal['electorate'])
        proposal['votes']=rows(db,'SELECT * FROM sk_votes WHERE proposal_id=?',(proposal['id'],))
        proposal['approvals']=rows(db,'SELECT * FROM sk_approvals WHERE proposal_id=?',(proposal['id'],))
    group['audit']=rows(db,'SELECT * FROM sk_audit WHERE group_id=? ORDER BY created DESC LIMIT 40',(gid,))
    from group_features import treasury_snapshot,active_handover
    group['treasury']=treasury_snapshot(db,group)
    if group['treasury']['handover']:
        group['treasury']['votes']=rows(db,'SELECT user_id,approve FROM sk_handover_votes WHERE handover_id=?',(group['treasury']['handover']['id'],))
    if active_handover(db,gid): group['canSettle']=False
    return group

def authenticate(db,token):
    result=row(db,'SELECT u.id,u.name,u.email FROM sk_sessions s JOIN sk_users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?',(digest(token),int(time.time())))
    if not result: raise Problem('Please sign in.',401)
    return result

def session(db,user_id):
    token=secrets.token_urlsafe(32)
    db.execute('INSERT INTO sk_sessions VALUES(?,?,?)',(digest(token),user_id,int(time.time())+604800))
    return token

def access(db,gid,user_id):
    group=row(db,'SELECT * FROM sk_groups WHERE id=?',(gid,))
    member=row(db,'SELECT * FROM sk_members WHERE group_id=? AND user_id=?',(gid,user_id))
    if not group or not member: raise Problem('Group not found.',404)
    return group,member

def proposal_create(db,group,kind,payload,actor):
    if row(db,"SELECT id FROM sk_proposals WHERE group_id=? AND kind=? AND status='pending'",(group['id'],kind)):
        raise Problem('A proposal of this type is already awaiting a decision.')
    electorate=[r['user_id'] for r in rows(db,"SELECT user_id FROM sk_members WHERE group_id=? AND status='active'",(group['id'],))]
    pid=uid(); cycle=current(db,group['id'])
    db.execute('INSERT INTO sk_proposals VALUES(?,?,?,?,?,?,?,?)',(pid,group['id'],kind,json.dumps(payload),'pending',core.now(),cycle['id'],json.dumps(electorate)))
    audit(db,group['id'],actor,'Proposed '+kind)
    return {'proposalId':pid}

def seed_demo(db, actor):
    alice = row(db, "SELECT * FROM sk_users WHERE email='alice@savekin.local'")
    if not alice:
        aid = uid()
        db.execute("INSERT INTO sk_users VALUES(?,?,?,?)", (aid, 'Alice (President)', 'alice@savekin.local', password_hash('demo-password-123')))
        alice = {'id': aid}
    bob = row(db, "SELECT * FROM sk_users WHERE email='bob@savekin.local'")
    if not bob:
        bid = uid()
        db.execute("INSERT INTO sk_users VALUES(?,?,?,?)", (bid, 'Bob (Treasurer)', 'bob@savekin.local', password_hash('demo-password-123')))
        bob = {'id': bid}
    charlie = row(db, "SELECT * FROM sk_users WHERE email='charlie@savekin.local'")
    if not charlie:
        cid = uid()
        db.execute("INSERT INTO sk_users VALUES(?,?,?,?)", (cid, 'Charlie (Member)', 'charlie@savekin.local', password_hash('demo-password-123')))
        charlie = {'id': cid}

    existing = row(db, "SELECT * FROM sk_groups WHERE name='Kigali Community Circle'")
    if existing:
        gid = existing['id']
    else:
        gid = uid(); cycle_id = uid()
        start = date.today() - timedelta(days=60)
        end = date.today()
        rules = {
            'sharePrice': 1000,
            'goal': 50000,
            'ending': 'repeat',
            'months': 6,
            'joining': 'catch_up',
            'fine': 100,
            'exitPenalty': 500,
            'surplus': 'distribute',
            'voting': 'Two-thirds majority'
        }
        db.execute("INSERT INTO sk_groups VALUES(?,?,?,?,?,?,?,?)",
            (gid, 'Kigali Community Circle', alice['id'], bob['id'], 'USD', json.dumps(rules), secrets.token_urlsafe(24), core.now()))
        db.execute("INSERT INTO sk_cycles VALUES(?,?,?,?,?,?,?)",
            (cycle_id, gid, 1, start.isoformat(), end.isoformat(), 'open', None))
        
        m_alice = uid(); m_bob = uid(); m_charlie = uid()
        db.execute("INSERT INTO sk_members VALUES(?,?,?,?,?,?,?)", (m_alice, gid, alice['id'], 'active', 2, None, core.now()))
        db.execute("INSERT INTO sk_members VALUES(?,?,?,?,?,?,?)", (m_bob, gid, bob['id'], 'active', 2, None, core.now()))
        db.execute("INSERT INTO sk_members VALUES(?,?,?,?,?,?,?)", (m_charlie, gid, charlie['id'], 'active', 1, None, core.now()))
        
        db.execute("INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)", (uid(), gid, cycle_id, m_alice, 'contribution', 4000, 'DEMO-ALICE-1', core.now()))
        db.execute("INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)", (uid(), gid, cycle_id, m_bob, 'treasury_contribution', 4000, 'DEMO-BOB-TREASURY', core.now()))
        db.execute("INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)", (uid(), gid, cycle_id, m_charlie, 'contribution', 1000, 'DEMO-CHARLIE-1', core.now()))
        
        db.execute("INSERT OR REPLACE INTO sk_payout_accounts VALUES(?,?)", (alice['id'], 'alice-payout@example.com'))
        db.execute("INSERT OR REPLACE INTO sk_payout_accounts VALUES(?,?)", (bob['id'], 'bob-payout@example.com'))
        db.execute("INSERT OR REPLACE INTO sk_payout_accounts VALUES(?,?)", (charlie['id'], 'charlie-payout@example.com'))
        db.execute("INSERT OR REPLACE INTO sk_receiving_accounts VALUES(?,?,?,?)", (gid, bob['id'], 'bob-treasury@example.com', core.now()))

        db.execute("INSERT INTO sk_discussions(group_id, user_id, sender_name, content, client_id, created, sent_at) VALUES(?,?,?,?,?,?,?)",
            (gid, alice['id'], 'Alice (President)', 'Welcome to our circle! Contributions and PayPal payouts will be settled here.', uid(), core.now(), time.time()))
    
    if actor:
        user_mem = row(db, "SELECT * FROM sk_members WHERE group_id=? AND user_id=?", (gid, actor))
        if not user_mem:
            mid = uid()
            db.execute("INSERT INTO sk_members VALUES(?,?,?,?,?,?,?)", (mid, gid, actor, 'active', 1, None, core.now()))
            c = current(db, gid)
            db.execute("INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)", (uid(), gid, c['id'], mid, 'contribution', 2000, 'DEMO-USER-INITIAL', core.now()))
            db.execute("INSERT OR REPLACE INTO sk_payout_accounts VALUES(?,?)", (actor, 'my-test-payout@example.com'))
        db.execute("INSERT INTO sk_preferences VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_group=excluded.last_group", (actor, gid))
        
    return {'ok': True, 'groupId': gid}

def dispatch(method,path,body,token=''):
    if method=='GET' and path not in ('/api/state','/api/assistant/chats') and not path.startswith(('/api/invite/','/api/assistant/chats/')):
        raise Problem('Use POST for this operation.',405)
    if path in ('/api/payouts/send','/api/payouts/check'):
        from payouts import operate
        return operate(path,body,token)
    with core.connect() as db:
        if path in ('/api/approve','/api/proposals','/api/paypal/orders','/api/discussions','/api/auth/reset-password') or path.startswith(('/api/profile','/api/treasury/')):
            db.execute('BEGIN IMMEDIATE')
        if path in ('/api/auth/forgot-password','/api/auth/reset-password'):
            from account_features import public
            return public(db,path,body)
        if path=='/api/auth/handoff':
            handoff=row(db,'SELECT * FROM sk_handoffs WHERE code=? AND expires>?',(digest(str(body.get('code',''))),int(time.time())))
            if not handoff: raise Problem('Checkout link expired or already used. Open checkout again from the mobile app.',401)
            db.execute('DELETE FROM sk_handoffs WHERE code=?',(handoff['code'],))
            return {'token':session(db,handoff['user_id']),'groupId':handoff['group_id']}
        if path in ('/api/auth/register','/api/auth/login'):
            email=clean(body.get('email',''),160).lower(); password=body.get('password','')
            if not isinstance(password,str) or not 10<=len(password)<=128: raise Problem('Use a password of 10–128 characters.')
            if '@' not in email or '.' not in email.split('@')[-1]: raise Problem('Enter a valid email address.')
            if path.endswith('register'):
                user_id=uid(); name=clean(body.get('name',''),80)
                db.execute('INSERT INTO sk_users VALUES(?,?,?,?)',(user_id,name,email,password_hash(password)))
            else:
                user=row(db,'SELECT * FROM sk_users WHERE email=?',(email,))
                if not user or not hmac.compare_digest(user['password'],password_hash(password,user['password'].split(':')[0])):
                    raise Problem('Email or password is incorrect.',401)
                user_id=user['id']
            return {'token':session(db,user_id),'user':row(db,'SELECT id,name,email FROM sk_users WHERE id=?',(user_id,))}
        if path.startswith('/api/invite/') and method=='GET':
            group=row(db,'SELECT * FROM sk_groups WHERE invite=?',(path.rsplit('/',1)[-1],))
            if not group: raise Problem('Invitation not found.',404)
            return {'id':group['id'],'name':group['name'],'rules':json.loads(group['rules']),'currency':group['currency'],
                'president':row(db,'SELECT name FROM sk_users WHERE id=?',(group['president'],))['name']}
        user=authenticate(db,token); actor=user['id']
        if path=='/api/auth/logout':
            db.execute('DELETE FROM sk_sessions WHERE token=?',(digest(token),)); return {'ok':True}
        if path=='/api/profile' or path.startswith('/api/profile/'):
            from account_features import handle
            return handle(db,path,body,actor,token)
        if path=='/api/notifications':
            from group_features import notifications
            items=notifications(db,actor)
            if body.get('read') is True:
                for item in items:
                    if not item['id'].startswith('discussion:'):
                        db.execute('INSERT OR IGNORE INTO sk_notification_reads VALUES(?,?)',(actor,item['id']))
                        item['unread']=False
            return {'items':items}
        if path=='/api/preferences':
            gid=body.get('groupId')
            if gid: access(db,gid,actor)
            db.execute('INSERT INTO sk_preferences VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_group=excluded.last_group',(actor,gid))
            return {'ok':True}
        if path=='/api/payout-account':
            import re
            email=clean(body.get('email',''),160).lower()
            if body.get('sandboxOnly') is not True or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
                raise Problem('Enter a sandbox PayPal email and confirm it is a test account.')
            if row(db,"SELECT b.cycle_id FROM sk_payout_batches b JOIN sk_members m ON m.group_id=b.group_id WHERE m.user_id=? AND b.status NOT IN ('complete')",(actor,)):
                raise Problem('A distribution is in progress. Its destination cannot be changed.')
            db.execute('INSERT INTO sk_payout_accounts VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email',(actor,email))
            return {'ok':True}
        if path=='/api/state':
            import ai_providers
            ids=rows(db,'SELECT group_id FROM sk_members WHERE user_id=?',(actor,))
            preference=row(db,'SELECT last_group FROM sk_preferences WHERE user_id=?',(actor,))
            last_group=preference['last_group'] if preference and preference['last_group'] in {r['group_id'] for r in ids} else None
            from account_features import profile
            from group_features import notifications
            return {'profile':profile(db,user),'notifications':notifications(db,actor),'mailReady':bool(core.os.environ.get('SMTP_HOST') or core.os.environ.get('SAVEKIN_MAIL_MODE')=='local'),'user':user,'payoutAccount':row(db,'SELECT email FROM sk_payout_accounts WHERE user_id=?',(actor,)),
              'lastGroupId':last_group,'assistantConsent':bool(row(db,'SELECT accepted FROM sk_ai_consents WHERE user_id=? AND provider=? AND version=?',(actor,ai_providers.provider(),'support-chat-v1'))),
              'groups':[snapshot(db,r['group_id']) for r in ids],
              'config':{'mode':core.MODE,'paypalClientId':core.os.environ.get('PAYPAL_CLIENT_ID','') if core.MODE=='sandbox' else '',
                        'sandboxRecipient':core.os.environ.get('PAYPAL_TREASURER_EMAIL',''),
                        'paypalReady':all(core.os.environ.get(k) for k in ('PAYPAL_CLIENT_ID','PAYPAL_CLIENT_SECRET','PAYPAL_TREASURER_EMAIL')),
                        'webhookReady':bool(core.os.environ.get('PAYPAL_WEBHOOK_ID')),
                        'assistantReady':ai_providers.ready(),'assistantProvider':ai_providers.provider()}}
        if path=='/api/demo/seed':
            return seed_demo(db, actor)
        if path=='/api/groups':
            currency=body.get('currency','USD')
            if currency not in ('USD','RWF'): raise Problem('Choose USD or RWF. PayPal sandbox currently supports USD only here.')
            rules=rules_from(body,currency); gid=uid(); cid=uid()
            start=date.today(); end=date.fromisoformat(body.get('end',''))
            if end<start: raise Problem('Choose a cycle end date today or later.')
            db.execute('INSERT INTO sk_groups VALUES(?,?,?,?,?,?,?,?)',(gid,clean(body.get('name',''),80),actor,None,currency,json.dumps(rules),secrets.token_urlsafe(24),core.now()))
            db.execute('INSERT INTO sk_cycles VALUES(?,?,?,?,?,?,?)',(cid,gid,1,start.isoformat(),end.isoformat(),'open',None))
            db.execute('INSERT INTO sk_members VALUES(?,?,?,?,?,?,?)',(uid(),gid,actor,'active',integer(body.get('shares',1)),None,core.now()))
            audit(db,gid,actor,'Created group and accepted founding rules')
            db.execute('INSERT INTO sk_preferences VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_group=excluded.last_group',(actor,gid))
            return {'id':gid}
        if path=='/api/join':
            group=row(db,'SELECT * FROM sk_groups WHERE invite=?',(body.get('invite'),))
            if not group: raise Problem('Invitation not found.',404)
            if body.get('acceptRules') is not True: raise Problem('You must accept the group rules.')
            from group_features import active_handover
            if active_handover(db,group['id']): raise Problem('Joining is paused during a treasurer handover.')
            cycle=current(db,group['id']); rules=json.loads(group['rules'])
            started=bool(row(db,'SELECT id FROM sk_ledger WHERE cycle_id=? LIMIT 1',(cycle['id'],)))
            status='waiting' if cycle['status']!='open' or (started and rules['joining']=='next_cycle') else 'active'
            db.execute('INSERT INTO sk_members VALUES(?,?,?,?,?,?,?)',(uid(),group['id'],actor,status,integer(body.get('shares',1)),None,core.now()))
            audit(db,group['id'],actor,'Joined group and accepted rules ('+status+')')
            db.execute('INSERT INTO sk_preferences VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_group=excluded.last_group',(actor,group['id']))
            return {'id':group['id'],'status':status}
        if path=='/api/assistant' or path.startswith('/api/assistant/'):
            from assistant_chat import handle
            return handle(db,method,path,body,actor)
        gid=body.get('groupId'); group,member=access(db,gid,actor)
        from group_features import active_handover,handle_treasury,discussion
        if path=='/api/discussions': return discussion(db,body,actor,group,member)
        if path.startswith('/api/treasury/') and path!='/api/treasury/evidence': return handle_treasury(db,path,body,actor,group)
        if active_handover(db,gid) and path not in ('/api/paypal/capture','/api/paypal/reconcile','/api/treasury/evidence'):
            raise Problem('Contributions, group changes and distributions are paused until treasurer handover completes.')
        rules=json.loads(group['rules']); cycle=current(db,gid)
        officer=actor in (group['president'],group['treasurer'])
        if path=='/api/treasury/evidence':
            proposal=row(db,"SELECT * FROM sk_proposals WHERE id=? AND group_id=? AND kind='treasury'",(body.get('proposalId'),gid))
            if not proposal: raise Problem('Evidence not found.',404)
            evidence=row(db,'SELECT * FROM sk_treasury_evidence WHERE proposal_id=?',(proposal['id'],))
            if not evidence: raise Problem('This request has a reference and note, but no attached file.',404)
            return {'name':evidence['name'],'mime':evidence['mime'],'data':base64.b64encode(evidence['data']).decode()}
        if path=='/api/paypal/quote':
            if core.MODE!='sandbox' or group['currency']!='USD': raise Problem('Fee estimates are available for USD sandbox checkout only.')
            if member['status']!='active' or cycle['status'] not in ('open','goal_reached'): raise Problem('Contributions are not open.')
            from fees import estimate
            quote=estimate(money(body.get('amount'))); quote_id=uid()
            db.execute('INSERT INTO sk_payment_quotes VALUES(?,?,?,?,?,?,?,?,NULL)',(quote_id,gid,cycle['id'],actor,quote['target'],quote['gross'],quote['fee'],int(time.time())+600))
            return {**quote,'quoteId':quote_id}
        if path=='/api/checkout-link':
            if core.MODE!='sandbox': raise Problem('Browser checkout is for sandbox payments.')
            code=secrets.token_urlsafe(32)
            db.execute('DELETE FROM sk_handoffs WHERE expires<=? OR user_id=?',(int(time.time()),actor))
            db.execute('INSERT INTO sk_handoffs VALUES(?,?,?,?)',(digest(code),actor,gid,int(time.time())+90))
            return {'code':code}
        if path=='/api/shares':
            count=integer(body.get('shares'))
            if member['status'] not in ('active','waiting') or cycle['status']!='open': raise Problem('Shares cannot change now.')
            if body.get('when')=='next':
                db.execute('UPDATE sk_members SET next_shares=? WHERE id=?',(count,member['id']))
                audit(db,gid,actor,'Scheduled '+str(count)+' shares for next cycle')
            else:
                if count<=member['shares']: raise Problem('Decrease shares next cycle or use the early-exit process.')
                # Increasing shares creates a catch-up obligation, but never fabricates a payment.
                db.execute('UPDATE sk_members SET shares=? WHERE id=?',(count,member['id']))
                audit(db,gid,actor,'Increased shares to '+str(count)+'; catch-up contributions now due')
            return {'ok':True}
        if path=='/api/paypal/reconcile':
            from payments import reconcile_order
            order=row(db,'SELECT * FROM sk_orders WHERE id=? AND user_id=? AND group_id=?',(body.get('orderId'),actor,gid))
            if not order: raise Problem('Payment order not found.',404)
            if core.MODE!='sandbox': raise Problem('Payment recovery is available in sandbox mode only.')
            return reconcile_order(db,order,actor)
        if path in ('/api/paypal/orders','/api/paypal/capture'):
            if core.MODE!='sandbox': raise Problem('Enable sandbox mode first.')
            if group['currency']!='USD': raise Problem('Sandbox checkout currently supports USD only.')
            if member['status']!='active' or not (cycle['status']=='open' or cycle['status']=='goal_reached' and amounts(db,member,cycle,rules)['arrears']>0): raise Problem('Contributions are not open for this member.')
            from group_features import receiving
            destination=receiving(db,group)
            recipient=destination['email']
            if not destination['ready']: raise Problem('The treasury receiving account needs sandbox server configuration before payments can be made.')
            if path.endswith('orders'):
                value=money(body.get('amount'))
                quote=None
                if body.get('quoteId'):
                    quote=row(db,'SELECT * FROM sk_payment_quotes WHERE id=? AND group_id=? AND cycle_id=? AND user_id=?',
                        (body['quoteId'],gid,cycle['id'],actor))
                    if not quote or quote['expires']<=int(time.time()) or quote['target']!=value: raise Problem('Fee estimate expired or amount changed. Calculate a new total.')
                    if quote['order_id']: return {'id':quote['order_id']}
                    value=quote['gross']
                token_pp=core.paypal('/v1/oauth2/token')['access_token']
                order=core.paypal('/v2/checkout/orders',{'intent':'CAPTURE','purchase_units':[{
                    'custom_id':gid+':'+member['id'],'payee':{'email_address':recipient},
                    'amount':{'currency_code':'USD','value':f'{value/100:.2f}'}}]},token_pp,uid())
                db.execute('INSERT INTO sk_orders VALUES(?,?,?,?,?,?,0)',(order['id'],gid,cycle['id'],member['id'],actor,value))
                db.execute('INSERT INTO sk_payment_state(order_id,recipient,status,updated) VALUES(?,?,?,?)',(order['id'],recipient,'created',core.now()))
                if quote: db.execute('UPDATE sk_payment_quotes SET order_id=? WHERE id=?',(order['id'],quote['id']))
                return {'id':order['id']}
            order=row(db,'SELECT * FROM sk_orders WHERE id=? AND user_id=? AND group_id=? AND cycle_id=?',
                (body.get('orderId'),actor,gid,cycle['id']))
            if not order: raise Problem('Payment order not found.',404)
            if order['captured']:
                state=row(db,'SELECT * FROM sk_payment_state WHERE order_id=?',(order['id'],))
                return {'ok':not bool(state and state['needs_review']), 'credited':True,
                    'status':state['status'] if state else 'completed','needsReview':bool(state and state['needs_review'])}
            token_pp=core.paypal('/v1/oauth2/token')['access_token']
            result=core.paypal('/v2/checkout/orders/'+order['id']+'/capture',{},token_pp,'capture-'+order['id'])
            unit=result['purchase_units'][0]; capture=unit['payments']['captures'][0]
            if (result['status'] not in ('COMPLETED','APPROVED') or capture['status'] not in ('COMPLETED','PENDING','DECLINED')
                or capture['amount']['currency_code']!='USD' or money(capture['amount']['value'])!=order['amount']
                or unit.get('payee',{}).get('email_address','').lower()!=recipient):
                raise Problem('PayPal has not confirmed the expected payment and recipient.')
            from payments import record_capture
            return record_capture(db,order,unit,capture,actor)
        if path in ('/api/contribute','/api/fine','/api/expense'):
            if core.MODE!='demo': raise Problem('Demo entries are disabled in sandbox mode.')
            if cycle['status'] not in ('open','goal_reached'): raise Problem('This cycle is closed to new entries.')
            if cycle['status']=='goal_reached' and path!='/api/contribute': raise Problem('Only outstanding contributions can be settled after reaching the goal.')
            target=member
            if path!='/api/contribute':
                if not officer: raise Problem('Only officers can record this item.',403)
                if path=='/api/fine':
                    target=row(db,"SELECT * FROM sk_members WHERE id=? AND group_id=? AND status='active'",(body.get('memberId'),gid))
                    if not target or not rules['fine']: raise Problem('Fines must be enabled in the accepted rules, for an active member.')
            if target['status']!='active': raise Problem('This member is not active in the current cycle.')
            kind={'/api/contribute':'contribution','/api/fine':'fine','/api/expense':'expense'}[path]
            value=rules['fine'] if kind=='fine' else money(body.get('amount'),group['currency'])
            if cycle['status']=='goal_reached' and value>amounts(db,target,cycle,rules)['arrears']:
                raise Problem('The goal is reached. Only the outstanding contribution amount can be paid.')
            if kind=='expense' and value>snapshot(db,gid)['pool']: raise Problem('Expense exceeds the recorded pool.')
            db.execute('INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)',(uid(),gid,cycle['id'],target['id'],kind,value,'DEMO-'+uid(),core.now()))
            audit(db,gid,actor,'Recorded demo '+kind)
            if rules['ending']=='goal' and snapshot(db,gid)['gross']>=rules['goal']:
                db.execute("UPDATE sk_cycles SET status='goal_reached' WHERE id=?",(cycle['id'],))
            return {'ok':True}
        if path=='/api/proposals':
            kind=body.get('kind')
            if kind=='treasury':
                if actor!=group['treasurer'] or actor==group['president']: raise Problem('Only the separate treasurer can request a treasury contribution.',403)
                if member['status']!='active' or cycle['status'] not in ('open','goal_reached'): raise Problem('Treasury contributions are closed during settlement.')
                if cycle['status']=='goal_reached' and amounts(db,member,cycle,rules)['arrears']==0: raise Problem('Only outstanding obligations can be settled after reaching the goal.')
                if body.get('confirmOwnFunds') is not True: raise Problem('Confirm you are allocating your own funds already in the treasury.')
                value=money(body.get('amount')); reference=clean(body.get('reference',''),160); note=clean(body.get('note',''),1000)
                if any(json.loads(p['payload']).get('reference','').casefold()==reference.casefold() for p in rows(db,"SELECT payload FROM sk_proposals WHERE group_id=? AND kind='treasury' AND status IN ('pending','accepted')",(gid,))):
                    raise Problem('That supporting reference has already been used for a treasury contribution.')
                if row(db,"SELECT id FROM sk_proposals WHERE group_id=? AND status='pending' AND kind IN ('president','treasurer')",(gid,)):
                    raise Problem('Finish pending officer changes first.')
                result=proposal_create(db,group,'treasury',{'memberId':member['id'],'requesterId':actor,'amount':value,
                    'reference':reference,'note':note,'verification':'Manual president confirmation; not PayPal verified'},actor)
                attachment=body.get('evidence')
                if attachment:
                    if not isinstance(attachment,dict): raise Problem('Invalid evidence attachment.')
                    try: data=base64.b64decode(attachment.get('data',''),validate=True)
                    except (ValueError,TypeError): raise Problem('Invalid evidence file.')
                    mime=attachment.get('mime'); signature={'image/png':b'\x89PNG\r\n\x1a\n','image/jpeg':b'\xff\xd8\xff','application/pdf':b'%PDF-'}
                    if mime not in signature or not data.startswith(signature[mime]) or not 0<len(data)<=262144:
                        raise Problem('Attach a PNG, JPEG or PDF up to 256 KB.')
                    db.execute('INSERT INTO sk_treasury_evidence VALUES(?,?,?,?)',(result['proposalId'],clean(attachment.get('name','evidence'),100),mime,data))
                return result
            if kind in ('rules','president','treasurer'):
                if actor!=group['president']: raise Problem('The president proposes rule and role changes.',403)
                if cycle['status']!='open': raise Problem('Finish settlement before changing rules or officers.')
                if kind in ('president','treasurer') and row(db,"SELECT id FROM sk_proposals WHERE group_id=? AND kind='treasury' AND status='pending'",(gid,)):
                    raise Problem('Resolve the treasury contribution before changing officers.')
                if kind=='rules':
                    payload=rules_from(body['rules'],group['currency'])
                    if payload['sharePrice']!=rules['sharePrice']: raise Problem('Share price stays fixed for this cycle. Create a new group for a different price in this version.')
                else:
                    target=row(db,"SELECT * FROM sk_members WHERE group_id=? AND user_id=? AND status='active'",(gid,body.get('userId')))
                    if not target: raise Problem('Choose an active member.')
                    other=group['treasurer'] if kind=='president' else group['president']
                    if target['user_id']==other: raise Problem('President and treasurer must be different people.')
                    payload={'userId':target['user_id']}
                return proposal_create(db,group,kind,payload,actor)
            if kind=='exit':
                if member['status']!='active' or officer: raise Problem('Officers must hand over their role before leaving.')
                if cycle['status']!='open': raise Problem('Wait until settlement completes.')
                account=amounts(db,member,cycle,rules)
                result=proposal_create(db,group,kind,{'memberId':member['id'],'principal':account['principal'],
                    'penalty':min(account['principal'],rules['exitPenalty']),
                    'amount':max(0,account['principal']-rules['exitPenalty'])},actor)
                db.execute("UPDATE sk_members SET status='exit_pending' WHERE id=?",(member['id'],))
                return result
            if kind=='settlement':
                if not officer: raise Problem('Only officers can propose a settlement.',403)
                snap=snapshot(db,gid)
                if not snap['canSettle']: raise Problem('Reach the goal or end date, resolve arrears, and appoint a separate treasurer before settlement.')
                allocations=snap['allocations']
                if core.MODE=='sandbox':
                    for allocation in allocations:
                        account=row(db,'SELECT a.email FROM sk_payout_accounts a JOIN sk_members m ON m.user_id=a.user_id WHERE m.id=?',(allocation['memberId'],))
                        if not account: raise Problem('Each recipient must set their sandbox payout email before settlement is proposed.')
                        allocation['receiver']=account['email']
                payload={'allocations':allocations,'pool':snap['pool'],'carried':snap['carried']}
                result=proposal_create(db,group,kind,payload,actor)
                db.execute("UPDATE sk_cycles SET status='review' WHERE id=?",(cycle['id'],))
                return result
            raise Problem('Unknown proposal type.')
        if path in ('/api/vote','/api/approve'):
            proposal=row(db,'SELECT * FROM sk_proposals WHERE id=? AND group_id=?',(body.get('proposalId'),gid))
            if not proposal or proposal['status']!='pending': raise Problem('This proposal is no longer pending.')
            payload=json.loads(proposal['payload']); kind=proposal['kind']
            if kind=='treasury':
                if path!='/api/approve' or actor!=group['president'] or actor==payload['requesterId']:
                    raise Problem('Only the separate president can approve or reject this treasury contribution.',403)
                if not isinstance(body.get('approve'),bool): raise Problem('Choose yes or no explicitly.')
                if proposal['cycle_id']!=cycle['id'] or cycle['status'] not in ('open','goal_reached') or group['treasurer']!=payload['requesterId']:
                    raise Problem('The cycle or treasurer changed. This request cannot be credited.')
                if body['approve']:
                    db.execute('INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)',(uid(),gid,cycle['id'],payload['memberId'],'treasury_contribution',payload['amount'],'MANUAL-'+proposal['id'],core.now()))
                    db.execute('INSERT INTO sk_approvals VALUES(?,?)',(proposal['id'],actor))
                    from payments import goal_status
                    goal_status(db,{'group_id':gid,'cycle_id':cycle['id']})
                db.execute('UPDATE sk_proposals SET status=? WHERE id=?',('accepted' if body['approve'] else 'rejected',proposal['id']))
                audit(db,gid,actor,('Manually confirmed' if body['approve'] else 'Rejected')+' treasury contribution '+proposal['id'])
                return {'ok':True}
            if path=='/api/vote':
                if kind not in ('rules','president','treasurer'): raise Problem('This decision requires officer approval.')
                electorate=json.loads(proposal['electorate'])
                if actor not in electorate: raise Problem('You are not eligible for this vote.',403)
                if not isinstance(body.get('approve'),bool): raise Problem('Choose yes or no.')
                db.execute('INSERT INTO sk_votes VALUES(?,?,?)',(proposal['id'],actor,int(body['approve'])))
                votes=rows(db,'SELECT * FROM sk_votes WHERE proposal_id=?',(proposal['id'],))
                yes=sum(v['approve'] for v in votes); n=len(electorate); cast=len(votes)
                target_consent=kind=='rules' or any(v['user_id']==payload['userId'] and v['approve'] for v in votes)
                # Approval must survive any remaining votes, avoiding order-dependent decisions.
                accepted=cast>=math.ceil(2*n/3) and yes>=math.ceil(2*n/3) and yes>n/2 and target_consent
                rejected=cast==n and not accepted
                if accepted:
                    if kind=='rules': db.execute('UPDATE sk_groups SET rules=? WHERE id=?',(json.dumps(payload),gid))
                    elif kind=='treasurer' and group['treasurer'] and group['treasurer']!=payload['userId']:
                        from group_features import start_handover
                        start_handover(db,group,payload['userId'],proposal['id'])
                    else:
                        db.execute('UPDATE sk_groups SET '+kind+'=? WHERE id=?',(payload['userId'],gid))
                        if kind=='treasurer':
                            db.execute('INSERT OR IGNORE INTO sk_receiving_accounts VALUES(?,?,?,?)',(gid,payload['userId'],'',core.now()))
                    db.execute("UPDATE sk_proposals SET status='accepted' WHERE id=?",(proposal['id'],))
                elif rejected: db.execute("UPDATE sk_proposals SET status='rejected' WHERE id=?",(proposal['id'],))
                audit(db,gid,actor,'Voted on '+kind)
            else:
                if kind not in ('exit','settlement') or not officer or not group['treasurer']: raise Problem('Both distinct officers must approve this decision.',403)
                if not isinstance(body.get('approve'),bool): raise Problem('Choose yes or no explicitly.')
                if body.get('approve') is False:
                    db.execute("UPDATE sk_proposals SET status='rejected' WHERE id=?",(proposal['id'],))
                    if kind=='settlement': db.execute("UPDATE sk_cycles SET status='open' WHERE id=?",(cycle['id'],))
                    if kind=='exit': db.execute("UPDATE sk_members SET status='active' WHERE id=?",(payload['memberId'],))
                    audit(db,gid,actor,'Rejected '+kind); return {'ok':True}
                db.execute('INSERT INTO sk_approvals VALUES(?,?)',(proposal['id'],actor))
                approvals=rows(db,'SELECT user_id FROM sk_approvals WHERE proposal_id=?',(proposal['id'],))
                if {group['president'],group['treasurer']}<={r['user_id'] for r in approvals}:
                    if kind=='settlement':
                        db.execute("UPDATE sk_cycles SET status='approved',settlement=? WHERE id=?",(json.dumps(payload),cycle['id']))
                    else:
                        # Approval prepares an exit. It does not claim that money has been sent.
                        db.execute("UPDATE sk_members SET status='exit_approved' WHERE id=?",(payload['memberId'],))
                    db.execute("UPDATE sk_proposals SET status='accepted' WHERE id=?",(proposal['id'],))
                audit(db,gid,actor,'Approved '+kind)
            return {'ok':True}
        if path=='/api/complete':
            if core.MODE!='demo': raise Problem('Automatic live payouts are not enabled. Demo settlement only.')
            if actor!=group['treasurer']: raise Problem('The treasurer completes approved demo distributions.',403)
            kind=body.get('kind')
            if kind=='exit':
                proposal=row(db,"SELECT * FROM sk_proposals WHERE id=? AND group_id=? AND kind='exit' AND status='accepted'",(body.get('proposalId'),gid))
                if not proposal: raise Problem('No approved exit found.')
                payload=json.loads(proposal['payload']); target=row(db,'SELECT * FROM sk_members WHERE id=?',(payload['memberId'],))
                if target['status']!='exit_approved': raise Problem('Exit already completed.')
                if payload['amount']>snapshot(db,gid)['pool']: raise Problem('Recorded funds are insufficient.')
                for entry,value in [('exit_principal',payload['principal']),('exit_penalty',payload['penalty'])]:
                    if value: db.execute('INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)',(uid(),gid,cycle['id'],target['id'],entry,value,'DEMO-'+uid(),core.now()))
                db.execute("UPDATE sk_members SET status='left' WHERE id=?",(target['id'],))
                db.execute("UPDATE sk_proposals SET status='completed' WHERE id=?",(proposal['id'],))
            else:
                if cycle['status']!='approved': raise Problem('Both officers must approve settlement first.')
                db.execute("UPDATE sk_cycles SET status='distributed' WHERE id=?",(cycle['id'],))
                audit(db,gid,actor,'Simulated distribution; no real payout sent')
            return {'ok':True}
        if path=='/api/next-cycle':
            if actor!=group['president']: raise Problem('Only the president starts the next cycle.',403)
            if cycle['status']!='distributed' or rules['ending']!='repeat': raise Problem('Complete distribution in a repeating group first.')
            cid=uid(); start=date.today(); month=start.month-1+rules['months']
            import calendar
            year=start.year+month//12; month=month%12+1
            end=date(year,month,min(start.day,calendar.monthrange(year,month)[1]))-timedelta(days=1)
            db.execute('INSERT INTO sk_cycles VALUES(?,?,?,?,?,?,?)',(cid,gid,cycle['number']+1,start.isoformat(),end.isoformat(),'open',None))
            db.execute("UPDATE sk_members SET shares=COALESCE(next_shares,shares),next_shares=NULL,status='active' WHERE group_id=? AND status IN ('active','waiting')",(gid,))
            settled=json.loads(cycle['settlement'])
            if settled.get('carried'):
                db.execute('INSERT INTO sk_ledger VALUES(?,?,?,?,?,?,?,?)',(uid(),gid,cid,member['id'],'carry',settled['carried'],'CARRY-'+cycle['id'],core.now()))
            audit(db,gid,actor,'Started cycle '+str(cycle['number']+1)); return {'ok':True}
        raise Problem('Endpoint not found.',404)

class Handler(core.Handler):
    failures={}
    def token(self):
        auth=self.headers.get('Authorization','')
        if auth.startswith('Bearer '): return auth[7:]
        cookie=SimpleCookie(); cookie.load(self.headers.get('Cookie',''))
        return cookie['savekin_session'].value if 'savekin_session' in cookie else ''
    def json(self,data,status=200):
        raw=json.dumps(data).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store')
        if isinstance(data,dict) and data.get('token'):
            secure='; Secure' if core.os.environ.get('RENDER')=='true' else ''
            self.send_header('Set-Cookie','savekin_session='+data['token']+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800'+secure)
        if self.path=='/api/auth/logout':
            secure='; Secure' if core.os.environ.get('RENDER')=='true' else ''
            self.send_header('Set-Cookie','savekin_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+secure)
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/healthz': return self.json({'ok':True})
        if not path.startswith('/api/'):
            if path in ('/join','/pay'): self.path='/'
            return super().do_GET()
        self.handle_api('GET',path,{})
    def do_POST(self):
        if urlparse(self.path).path=='/api/paypal/webhook':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256000: raise Problem('Invalid webhook size.')
                event=json.loads(self.rfile.read(length))
                if not isinstance(event,dict): raise Problem('Expected a webhook object.')
                from payments import webhook
                return self.json(webhook(dict(self.headers),event))
            except Problem as exc: return self.json({'error':str(exc)},exc.status)
            except (ValueError,TypeError,KeyError): return self.json({'error':'Invalid webhook payload.'},400)
            except (core.urllib.error.URLError,TimeoutError): return self.json({'error':'Provider verification is temporarily unavailable; retry delivery.'},503)
            except Exception:
                self.log_error('Webhook reconciliation failed; delivery can be retried')
                return self.json({'error':'Webhook was not processed; retry delivery.'},500)
        host=self.headers.get('Host','')
        if host not in core.allowed_hosts():
            return self.json({'error':'Unrecognized host.'},403)
        origin=self.headers.get('Origin')
        if origin and origin not in core.allowed_origins():
            return self.json({'error':'Cross-origin write blocked.'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            limit=380000 if urlparse(self.path).path in ('/api/proposals','/api/profile') else 20000
            if not 0<length<=limit: raise Problem('Invalid request size.')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise Problem('Expected a JSON object.')
            return self.handle_api('POST',urlparse(self.path).path,body)
        except (ValueError,TypeError) as exc: return self.json({'error':str(exc)},400)
    def handle_api(self,method,path,body):
        key=self.client_address[0]; now=time.time()
        if path.startswith('/api/auth/'):
            recent=[stamp for stamp in self.failures.get(key,[]) if now-stamp<60]
            self.failures[key]=recent
            if len(recent)>=12: return self.json({'error':'Too many sign-in attempts. Try again in a minute.'},429)
        try:
            result=dispatch(method,path,body,self.token())
            return self.json(result)
        except Problem as exc:
            if path.startswith('/api/auth/'): self.failures.setdefault(key,[]).append(now)
            return self.json({'error':str(exc)},exc.status)
        except core.sqlite3.IntegrityError:
            return self.json({'error':'This account, membership or decision already exists.'},409)
        except core.urllib.error.HTTPError as exc:
            self.log_error('Provider request rejected (HTTP %s)',exc.code)
            return self.json({'error':f'Provider rejected the request (HTTP {exc.code}). Payment outcome is unconfirmed; check status before retrying a payment.'},502)
        except (core.urllib.error.URLError,TimeoutError):
            self.log_error('Provider connection failed or timed out')
            return self.json({'error':'Could not reach the provider. Payment outcome is unconfirmed; try checking status again.'},503)
        except (ValueError,KeyError,TypeError): return self.json({'error':'Check the required fields and try again.'},400)
        except Exception:
            self.log_error('API request failed')
            return self.json({'error':'The request could not be completed. No successful payment is implied.'},500)
