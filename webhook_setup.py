"""Register the existing verified webhook handler with a sandbox PayPal app.

Run interactively; credentials are hidden where appropriate and never saved.
Provide an HTTPS relay which exposes ONLY /api/paypal/webhook, not the workspace.
"""
import getpass
import json
import os
import re
import warnings
from urllib.parse import urlparse
import server as core

EVENTS=['CHECKOUT.ORDER.APPROVED','PAYMENT.CAPTURE.COMPLETED','PAYMENT.CAPTURE.PENDING',
    'PAYMENT.CAPTURE.DENIED','PAYMENT.CAPTURE.REFUNDED','PAYMENT.CAPTURE.REVERSED',
    'PAYMENT.PAYOUTSBATCH.SUCCESS','PAYMENT.PAYOUTSBATCH.DENIED','PAYMENT.PAYOUTSBATCH.PROCESSING',
    'PAYMENT.PAYOUTS-ITEM.SUCCEEDED','PAYMENT.PAYOUTS-ITEM.FAILED',
    'PAYMENT.PAYOUTS-ITEM.UNCLAIMED','PAYMENT.PAYOUTS-ITEM.RETURNED',
    'PAYMENT.PAYOUTS-ITEM.REFUNDED','PAYMENT.PAYOUTS-ITEM.BLOCKED',
    'PAYMENT.PAYOUTS-ITEM.CANCELED','PAYMENT.PAYOUTS-ITEM.HELD']

def register(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.path!='/api/paypal/webhook' or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Use a public HTTPS URL ending in /api/paypal/webhook, without query parameters.')
    token=core.paypal('/v1/oauth2/token')['access_token']
    existing=core.paypal('/v1/notifications/webhooks',token=token,method='GET')
    for hook in existing.get('webhooks',[]):
        if hook.get('url')==url:
            raise ValueError('That URL is already registered. Use its existing Webhook ID, or update its events in the PayPal dashboard.')
    result=core.paypal('/v1/notifications/webhooks',{'url':url,'event_types':[{'name':name} for name in EVENTS]},token)
    identifier=result.get('id','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identifier): raise ValueError('PayPal did not return a webhook ID.')
    return identifier

def main():
    previous={k:os.environ.get(k) for k in ('PAYPAL_CLIENT_ID','PAYPAL_CLIENT_SECRET')}
    try:
        url=input('Public HTTPS webhook URL: ').strip()
        os.environ['PAYPAL_CLIENT_ID']=input('Sandbox app Client ID: ').strip()
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            os.environ['PAYPAL_CLIENT_SECRET']=getpass.getpass('Sandbox app Secret (hidden): ').strip()
        print('Webhook ID:',register(url))
        print('Restart SaveKin and enter this ID at its Webhook ID prompt. This does not create a public relay.')
        return 0
    except (KeyboardInterrupt,EOFError): print('Setup cancelled.'); return 1
    except ValueError as exc: print(str(exc)); return 1
    except Exception: print('Sandbox webhook registration failed. Check the app credentials and public URL. No secret was printed.'); return 1
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value

if __name__=='__main__': raise SystemExit(main())
