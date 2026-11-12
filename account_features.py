"""Account settings and expiring, single-use email challenges."""
import base64
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
import savekin as sk


def email(value):
    value=sk.clean(value,160).lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
        raise sk.Problem('Enter a valid email address.')
    return value


def profile(db,user):
    record=sk.row(db,'SELECT photo,verified_email FROM sk_profiles WHERE user_id=?',(user['id'],)) or {}
    return {'photo':record.get('photo'),'emailVerified':record.get('verified_email')==user['email']}


def deliver(address,code,kind):
    message=EmailMessage()
    message['Subject']='SaveKin: '+('reset your password' if kind=='reset' else 'verify your email')
    message['From']=os.environ.get('SMTP_FROM','savekin@localhost')
    message['To']=address
    message.set_content(f'Your SaveKin code is:\n\n{code}\n\nIt expires in 15 minutes and can be used once. If you did not request it, ignore this message.')
    if os.environ.get('SAVEKIN_MAIL_MODE')=='local':
        directory=sk.core.DB.parent/'mail-preview'
        directory.mkdir(parents=True,exist_ok=True)
        (directory/(secrets.token_hex(12)+'.eml')).write_bytes(message.as_bytes())
        return 'local'
    host=os.environ.get('SMTP_HOST')
    if not host: raise sk.Problem('Email delivery is not configured. Ask the administrator to configure SMTP or local development mail previews.',503)
    try:
        port=int(os.environ.get('SMTP_PORT','465'))
        if os.environ.get('SMTP_SECURITY','ssl')=='starttls':
            connection=smtplib.SMTP(host,port,timeout=15)
            connection.starttls(context=ssl.create_default_context())
        else: connection=smtplib.SMTP_SSL(host,port,timeout=15,context=ssl.create_default_context())
        with connection as smtp:
            if os.environ.get('SMTP_USER'): smtp.login(os.environ['SMTP_USER'],os.environ.get('SMTP_PASSWORD',''))
            smtp.send_message(message)
    except (OSError,smtplib.SMTPException,ValueError):
        raise sk.Problem('Email could not be delivered. Please try again later.',503)
    return 'email'


def issue(db,user,kind,address):
    previous=sk.row(db,'SELECT created FROM sk_email_codes WHERE user_id=? AND kind=?',(user['id'],kind))
    if previous and time.time()-previous['created']<60: raise sk.Problem('Wait a minute before requesting another code.',429)
    code=secrets.token_urlsafe(24) if kind=='reset' else f'{secrets.randbelow(1000000):06d}'
    delivery=deliver(address,code,kind)
    db.execute('INSERT OR REPLACE INTO sk_email_codes VALUES(?,?,?,?,?,?,?,?,?)',
        (user['id'],kind,address,sk.digest(code),int(time.time())+900,0,int(time.time()),user['password'],delivery))
    return {'ok':True,'delivery':delivery,'message':'Development email saved in the local mail-preview folder; no email was sent.' if delivery=='local' else 'Check your email for a code.'}


def consume(db,user,kind,code):
    record=sk.row(db,'SELECT * FROM sk_email_codes WHERE user_id=? AND kind=?',(user['id'],kind))
    if not record or record['expires']<=time.time() or record['attempts']>=5 or record['password_version']!=user['password']:
        return None
    if not hmac.compare_digest(record['code'],sk.digest(str(code))):
        db.execute('UPDATE sk_email_codes SET attempts=attempts+1 WHERE user_id=? AND kind=?',(user['id'],kind))
        return None
    db.execute('DELETE FROM sk_email_codes WHERE user_id=? AND kind=?',(user['id'],kind))
    return record


def public(db,path,body):
    address=email(body.get('email',''))
    user=sk.row(db,'SELECT * FROM sk_users WHERE email=?',(address,))
    if path=='/api/auth/forgot-password':
        # Same response for existing and unknown accounts. Delivery errors are not exposed.
        if user:
            try: issue(db,user,'reset',address)
            except sk.Problem: pass
        return {'ok':True,'message':'If this account exists and email delivery is configured, a reset code has been sent. Development previews appear in the local mail-preview folder.'}
    password=body.get('password','')
    if not isinstance(password,str) or not 10<=len(password)<=128: raise sk.Problem('Use a password of 10–128 characters.')
    record=consume(db,user,'reset',body.get('code','')) if user else None
    if not record: return {'ok':False,'error':'Invalid or expired reset code. Request a new one.'}
    db.execute('UPDATE sk_users SET password=? WHERE id=?',(sk.password_hash(password),user['id']))
    db.execute('DELETE FROM sk_sessions WHERE user_id=?',(user['id'],))
    db.execute('DELETE FROM sk_email_codes WHERE user_id=?',(user['id'],))
    return {'ok':True}


def handle(db,path,body,actor,token):
    user=sk.row(db,'SELECT * FROM sk_users WHERE id=?',(actor,))
    if path=='/api/profile':
        name=sk.clean(body.get('name',user['name']),80)
        photo=body.get('photo',profile(db,user)['photo'])
        if photo is not None:
            if not isinstance(photo,str) or len(photo)>180000: raise sk.Problem('Choose a PNG or JPEG profile photo up to 128 KB.')
            try:
                prefix,data=photo.split(',',1); raw=base64.b64decode(data,validate=True)
            except (ValueError,TypeError): raise sk.Problem('Invalid profile photo.')
            if len(raw)>131072 or not ((prefix=='data:image/png;base64' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (prefix=='data:image/jpeg;base64' and raw.startswith(b'\xff\xd8\xff'))):
                raise sk.Problem('Choose a PNG or JPEG profile photo up to 128 KB.')
        db.execute('UPDATE sk_users SET name=? WHERE id=?',(name,actor))
        db.execute('INSERT INTO sk_profiles(user_id,photo) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET photo=excluded.photo',(actor,photo))
        return {'ok':True}
    if path=='/api/profile/password':
        old=body.get('currentPassword',''); new=body.get('password','')
        if not isinstance(old,str) or not hmac.compare_digest(user['password'],sk.password_hash(old,user['password'].split(':')[0])):
            raise sk.Problem('Current password is incorrect.',403)
        if not isinstance(new,str) or not 10<=len(new)<=128: raise sk.Problem('Use a password of 10–128 characters.')
        db.execute('UPDATE sk_users SET password=? WHERE id=?',(sk.password_hash(new),actor))
        db.execute('DELETE FROM sk_sessions WHERE user_id=? AND token<>?',(actor,sk.digest(token)))
        db.execute('DELETE FROM sk_email_codes WHERE user_id=?',(actor,))
        return {'ok':True}
    if path=='/api/profile/email-request':
        old=body.get('currentPassword','')
        if not isinstance(old,str) or not hmac.compare_digest(user['password'],sk.password_hash(old,user['password'].split(':')[0])):
            raise sk.Problem('Confirm your current password.',403)
        address=email(body.get('email',user['email']))
        if sk.row(db,'SELECT id FROM sk_users WHERE email=? AND id<>?',(address,actor)): raise sk.Problem('That email cannot be used.')
        return issue(db,user,'verify',address)
    if path=='/api/profile/email-confirm':
        if sk.row(db,'SELECT g.id FROM sk_groups g LEFT JOIN sk_receiving_accounts a ON a.group_id=g.id AND a.user_id=g.treasurer WHERE g.treasurer=? AND a.group_id IS NULL LIMIT 1',(actor,)):
            raise sk.Problem('First declare your receiving account in Group treasury. Changing your SaveKin email must not change the treasury destination.')
        record=consume(db,user,'verify',body.get('code',''))
        if not record: return {'ok':False,'error':'Invalid or expired verification code.'}
        db.execute('UPDATE sk_users SET email=? WHERE id=?',(record['email'],actor))
        db.execute('INSERT INTO sk_profiles(user_id,verified_email) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET verified_email=excluded.verified_email',(actor,record['email']))
        db.execute('DELETE FROM sk_sessions WHERE user_id=? AND token<>?',(actor,sk.digest(token)))
        db.execute('DELETE FROM sk_email_codes WHERE user_id=?',(actor,))
        return {'ok':True}
    raise sk.Problem('Profile operation not found.',404)
