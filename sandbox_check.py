"""Check locally supplied sandbox credentials without printing credentials or access tokens."""
import os
import urllib.error
import server


def check():
    required=('PAYPAL_CLIENT_ID','PAYPAL_CLIENT_SECRET','PAYPAL_TREASURER_EMAIL')
    if not all(os.environ.get(name,'').strip() for name in required):
        print('Sandbox check failed: client ID, secret and treasurer email are required.')
        return 1
    try:
        response=server.paypal('/v1/oauth2/token')
    except urllib.error.HTTPError as exc:
        status=exc.code
        exc.close()
        print('Sandbox authentication failed (HTTP '+str(status)+'). Check your sandbox app credentials.')
        return 1
    except (urllib.error.URLError,TimeoutError,OSError,ValueError):
        print('Sandbox authentication could not complete. Check your connection and try again.')
        return 1
    if not isinstance(response,dict) or not response.get('access_token'):
        print('Sandbox authentication returned no access token. The server was not started.')
        return 1
    print('Sandbox app authentication: passed. No payment was created.')
    print('Checkout will verify the payment recipient. This is not multi-treasurer account ownership verification.')
    if os.environ.get('PAYPAL_WEBHOOK_ID','').strip():
        print('Webhook ID: supplied. Actual HTTPS delivery still needs testing.')
    else:
        print('Webhook ID: not supplied. Browser checkout can be tested; webhook delivery cannot yet be tested.')
    return 0


if __name__=='__main__':
    raise SystemExit(check())
