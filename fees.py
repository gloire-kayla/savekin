"""Disclosed sandbox fee estimates, never a promise of provider pricing."""
import os
import savekin as sk

def estimate(target):
    try:
        bps=int(os.environ.get('PAYPAL_FEE_BPS','349'))
        fixed=int(os.environ.get('PAYPAL_FEE_FIXED_CENTS','49'))
    except ValueError: raise sk.Problem('Sandbox fee configuration is invalid.',503)
    if not 0<=bps<5000 or not 0<=fixed<=10000:
        raise sk.Problem('Sandbox fee configuration is invalid.',503)
    # Integer half-up rounding; find the minimum charge whose estimated net meets target.
    fee=lambda total:(total*bps+5000)//10000+fixed
    low=target; high=(target+fixed)*2+2
    while low<high:
        middle=(low+high)//2
        if middle-fee(middle)>=target: high=middle
        else: low=middle+1
    return {'target':target,'gross':low,'fee':fee(low),'estimatedNet':low-fee(low),
        'basisPoints':bps,'fixedCents':fixed,'estimateOnly':True}
