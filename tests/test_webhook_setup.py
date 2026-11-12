import unittest
from unittest.mock import patch
import webhook_setup as setup

class WebhookSetupTests(unittest.TestCase):
    def test_invalid_urls_never_contact_provider(self):
        for url in ('http://example.com/api/paypal/webhook','https://example.com/','https://user:pass@example.com/api/paypal/webhook','https://example.com/api/paypal/webhook?secret=x'):
            with self.subTest(url=url),patch.object(setup.core,'paypal') as provider:
                with self.assertRaises(ValueError): setup.register(url)
                provider.assert_not_called()

    def test_existing_registration_is_not_duplicated(self):
        url='https://example.com/api/paypal/webhook'
        with patch.object(setup.core,'paypal',side_effect=[{'access_token':'mock'},{'webhooks':[{'url':url}]}]) as provider:
            with self.assertRaises(ValueError): setup.register(url)
            self.assertEqual(provider.call_count,2)

    def test_registers_capture_and_payout_notifications(self):
        with patch.object(setup.core,'paypal',side_effect=[{'access_token':'mock'},{'webhooks':[]},{'id':'WH-123'}]) as provider:
            self.assertEqual(setup.register('https://example.com/api/paypal/webhook'),'WH-123')
            body=provider.call_args.args[1]
            names={e['name'] for e in body['event_types']}
            self.assertIn('PAYMENT.CAPTURE.COMPLETED',names)
            self.assertIn('PAYMENT.PAYOUTS-ITEM.RETURNED',names)
