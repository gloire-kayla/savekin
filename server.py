"""Ikimina local development server. Python 3.11+, no external dependencies."""
import base64
import json
import os
import secrets
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _load_env_file():
    env_file = ROOT / '.env'
    if env_file.is_file():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

_load_env_file()
DB = Path(os.environ.get('GATHERSAVE_DATA_DIR', str(ROOT / 'data'))) / 'gathersave.sqlite3'
DB.parent.mkdir(exist_ok=True)
MODE = os.environ.get('PAYMENT_MODE', 'demo')
if MODE not in ('demo', 'sandbox'):
    raise RuntimeError('PAYMENT_MODE must be demo or sandbox. Live payments are not supported.')

@contextmanager
def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        with db:
            yield db
    finally:
        db.close()

with connect() as db:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS groups (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, goal INTEGER NOT NULL,
      contribution INTEGER NOT NULL, deadline TEXT NOT NULL,
      treasurer TEXT NOT NULL, invite TEXT UNIQUE NOT NULL, created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS members (
      id TEXT PRIMARY KEY, group_id TEXT REFERENCES groups(id),
      name TEXT NOT NULL, email TEXT NOT NULL, UNIQUE(group_id,email));
    CREATE TABLE IF NOT EXISTS payments (
      id TEXT PRIMARY KEY, group_id TEXT REFERENCES groups(id),
      member_id TEXT REFERENCES members(id), amount INTEGER NOT NULL,
      kind TEXT NOT NULL, reference TEXT UNIQUE NOT NULL, created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS orders (
      id TEXT PRIMARY KEY, group_id TEXT NOT NULL, member_id TEXT NOT NULL,
      amount INTEGER NOT NULL, captured INTEGER NOT NULL DEFAULT 0);
    ''')

def now():
    return datetime.now(timezone.utc).isoformat()

def paypal(path, payload=None, token=None, request_id=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    else:
        client = os.environ.get('PAYPAL_CLIENT_ID', '')
        secret = os.environ.get('PAYPAL_CLIENT_SECRET', '')
        if not client or not secret:
            raise ValueError('PayPal sandbox credentials are not configured.')
        headers['Authorization'] = 'Basic ' + base64.b64encode(f'{client}:{secret}'.encode()).decode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if request_id:
        headers['PayPal-Request-Id'] = request_id
    data = (json.dumps(payload).encode() if token else b'grant_type=client_credentials')
    if method == 'GET': data = None
    req = urllib.request.Request('https://api-m.sandbox.paypal.com' + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)

def amount(value):
    # All money is stored in integer cents; reject fractional cents and non-finite inputs.
    from decimal import Decimal, InvalidOperation
    try:
        val = Decimal(str(value)) * 100
        if not val.is_finite() or val != val.to_integral_value() or val <= 0 or val > 100000000:
            raise ValueError('Enter an amount between $0.01 and $1,000,000, with at most two decimals.')
        return int(val)
    except InvalidOperation:
        raise ValueError('Enter a valid money amount.')

class Handler(BaseHTTPRequestHandler):
    def json(self, data, status=200):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        route = self.path.split('?')[0]
        if route == '/api/state':
            with connect() as db:
                data = {key: [dict(r) for r in db.execute('SELECT * FROM ' + key)]
                        for key in ('groups', 'members', 'payments')}
            data['config'] = {'mode': MODE, 'paypalClientId': os.environ.get('PAYPAL_CLIENT_ID', '') if MODE == 'sandbox' else ''}
            return self.json(data)
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                 '/helper.js': ('helper.js', 'text/javascript'), '/workspace.js': ('workspace.js', 'text/javascript'),
                 '/styles.css': ('styles.css', 'text/css')}
        if route not in files:
            return self.json({'error': 'Not found'}, 404)
        filename, mime = files[route]
        raw = (ROOT / 'web' / filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        # Local-only development workspace. Reject cross-origin writes and DNS rebinding.
        host = self.headers.get('Host', '')
        if host not in ('127.0.0.1:8000', 'localhost:8000', '10.0.2.2:8000'):
            return self.json({'error': 'Local access only'}, 403)
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:8000', 'http://localhost:8000'):
            return self.json({'error': 'Cross-origin write blocked'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length > 20000:
                raise ValueError('Request is too large.')
            body = json.loads(self.rfile.read(length))
            route = self.path
            with connect() as db:
                if route == '/api/groups':
                    name = str(body.get('name', '')).strip()[:80]
                    treasurer = str(body.get('treasurer', '')).strip()[:80]
                    if not name or not treasurer:
                        raise ValueError('Group name and treasurer are required.')
                    deadline = str(body.get('deadline', ''))
                    datetime.strptime(deadline, '%Y-%m-%d')
                    gid = secrets.token_hex(8)
                    db.execute('INSERT INTO groups VALUES (?,?,?,?,?,?,?,?)',
                               (gid, name, amount(body.get('goal')), amount(body.get('contribution')),
                                deadline, treasurer, secrets.token_urlsafe(18), now()))
                    return self.json({'id': gid}, 201)
                gid = body.get('groupId')
                group = db.execute('SELECT * FROM groups WHERE id=?', (gid,)).fetchone()
                if not group:
                    raise ValueError('Choose an existing group.')
                if route == '/api/members':
                    name = str(body.get('name', '')).strip()[:80]
                    email = str(body.get('email', '')).strip().lower()[:160]
                    if not name or '@' not in email or '.' not in email.split('@')[-1]:
                        raise ValueError('Enter a member name and valid email.')
                    db.execute('INSERT INTO members VALUES (?,?,?,?)', (secrets.token_hex(8), gid, name, email))
                    return self.json({'ok': True}, 201)
                member = db.execute('SELECT * FROM members WHERE id=? AND group_id=?',
                                    (body.get('memberId'), gid)).fetchone()
                if not member:
                    raise ValueError('Choose a member of this group.')
                if route == '/api/payments/demo':
                    if MODE != 'demo':
                        raise ValueError('Demo payments are disabled in sandbox mode.')
                    value = amount(body.get('amount'))
                    db.execute('INSERT INTO payments VALUES (?,?,?,?,?,?,?)',
                               (secrets.token_hex(8), gid, member['id'], value, 'demo', 'DEMO-' + secrets.token_hex(6), now()))
                    return self.json({'ok': True}, 201)
                if route == '/api/paypal/orders':
                    if MODE != 'sandbox':
                        raise ValueError('Enable sandbox mode to use PayPal.')
                    value = amount(body.get('amount'))
                    token = paypal('/v1/oauth2/token')['access_token']
                    order = paypal('/v2/checkout/orders', {'intent': 'CAPTURE', 'purchase_units': [{
                        'custom_id': gid + ':' + member['id'],
                        'amount': {'currency_code': 'USD', 'value': f'{value / 100:.2f}'}}]}, token, secrets.token_hex(16))
                    db.execute('INSERT INTO orders VALUES (?,?,?,?,0)', (order['id'], gid, member['id'], value))
                    return self.json({'id': order['id']})
                if route == '/api/paypal/capture':
                    if MODE != 'sandbox':
                        raise ValueError('Sandbox mode is required.')
                    order = db.execute('SELECT * FROM orders WHERE id=? AND group_id=? AND member_id=?',
                                       (body.get('orderId'), gid, member['id'])).fetchone()
                    if not order:
                        raise ValueError('Unknown payment order.')
                    if order['captured']:
                        return self.json({'ok': True})
                    token = paypal('/v1/oauth2/token')['access_token']
                    result = paypal('/v2/checkout/orders/' + order['id'] + '/capture', {}, token, 'capture-' + order['id'])
                    capture = result['purchase_units'][0]['payments']['captures'][0]
                    if (result['status'] != 'COMPLETED' or capture['status'] != 'COMPLETED'
                        or capture['amount']['currency_code'] != 'USD'
                        or amount(capture['amount']['value']) != order['amount']):
                        raise ValueError('Payment is not confirmed with the expected amount.')
                    db.execute('INSERT OR IGNORE INTO payments VALUES (?,?,?,?,?,?,?)',
                               (secrets.token_hex(8), gid, member['id'], order['amount'], 'sandbox', capture['id'], now()))
                    db.execute('UPDATE orders SET captured=1 WHERE id=?', (order['id'],))
                    return self.json({'ok': True})
                return self.json({'error': 'Not found'}, 404)
        except sqlite3.IntegrityError:
            return self.json({'error': 'This member or payment is already recorded.'}, 409)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return self.json({'error': str(exc)}, 400)
        except urllib.error.HTTPError:
            return self.json({'error': 'PayPal did not approve this request. Check sandbox credentials and account eligibility.'}, 502)
        except Exception:
            self.log_error('Request failed; inspect local configuration.')
            return self.json({'error': 'Request could not be completed. Check the server configuration.'}, 500)

if __name__ == '__main__':
    from savekin import Handler as SaveKinHandler
    print('SaveKin is running at http://127.0.0.1:8000', flush=True)
    print('Development only. Demo/sandbox payments; keep real funds out.', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8000), SaveKinHandler).serve_forever()
