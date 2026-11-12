import contextlib
import io
import os
import unittest
from unittest.mock import patch
import start_sandbox as launcher


class SandboxLauncherTests(unittest.TestCase):
    def test_timed_out_probe_checks_windows_listeners(self):
        for output,expected in [('',False),('  TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    123\n',True)]:
            with self.subTest(expected=expected),patch.object(launcher.socket,'create_connection',side_effect=TimeoutError),patch.object(launcher.os,'name','nt'),patch.object(launcher.subprocess,'check_output',return_value=output):
                self.assertEqual(launcher.running(),expected)

    def invoke(self,valid=0,check_only=False,occupied=True):
        output=io.StringIO()
        args=['--check-only'] if check_only else ['--restart-local']
        with patch.object(launcher,'running',return_value=occupied),patch('builtins.input',side_effect=['test-client','test@example.com','']),patch.object(launcher.getpass,'getpass',return_value='private-secret'),patch.object(launcher,'validate_credentials',return_value=valid),patch.object(launcher,'stop_verified_server') as stop,patch.object(launcher.subprocess,'call',return_value=0) as run,contextlib.redirect_stdout(output):
            status=launcher.main(args)
        self.assertNotIn('private-secret',output.getvalue())
        return status,stop,run

    def test_invalid_credentials_leave_running_server_untouched(self):
        status,stop,run=self.invoke(valid=1)
        self.assertEqual(status,1); stop.assert_not_called(); run.assert_not_called()

    def test_check_only_never_restarts_server(self):
        status,stop,run=self.invoke(check_only=True)
        self.assertEqual(status,0); stop.assert_not_called(); run.assert_not_called()

    def test_explicit_restart_launches_python_directly(self):
        status,stop,run=self.invoke()
        self.assertEqual(status,0); stop.assert_called_once(); run.assert_called_once()
        args=run.call_args.args[0]
        self.assertEqual(args[0],launcher.sys.executable)
        self.assertTrue(args[1].endswith('server.py'))
        self.assertNotIn('private-secret',' '.join(args))

    def test_validation_restores_environment(self):
        with patch.dict(os.environ,{'PAYPAL_CLIENT_SECRET':'original'}),patch.object(launcher.sandbox_check,'check',return_value=0):
            self.assertEqual(launcher.validate_credentials({'PAYPAL_CLIENT_SECRET':'temporary'}),0)
            self.assertEqual(os.environ['PAYPAL_CLIENT_SECRET'],'original')

    def test_incomplete_ai_setup_does_not_stop_existing_server(self):
        with patch.object(launcher,'running',return_value=True),patch('builtins.input',side_effect=['client','test@example.com','','']),patch.object(launcher.getpass,'getpass',side_effect=['paypal-secret','']),patch.object(launcher,'validate_credentials',return_value=0),patch.object(launcher,'stop_verified_server') as stop,patch.object(launcher.subprocess,'call') as run,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launcher.main(['--restart-local','--with-ai']),1)
        stop.assert_not_called(); run.assert_not_called()
        self.assertNotIn('paypal-secret',output.getvalue())

    def test_failed_elastic_connection_does_not_stop_existing_server(self):
        import elastic_setup
        with patch.object(launcher,'running',return_value=True),patch('builtins.input',side_effect=['client','test@example.com','','https://a.elastic.cloud','']),patch.object(launcher.getpass,'getpass',side_effect=['paypal-secret','elastic-secret']),patch.object(launcher,'validate_credentials',return_value=0),patch.object(elastic_setup,'configure',side_effect=ValueError('denied')),patch.object(launcher,'stop_verified_server') as stop,patch.object(launcher.subprocess,'call') as run,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launcher.main(['--restart-local','--with-elastic']),1)
        stop.assert_not_called(); run.assert_not_called()
        self.assertNotIn('elastic-secret',output.getvalue())

    def test_local_mail_flag_is_explicit_and_child_only(self):
        with patch.object(launcher,'running',return_value=False),patch('builtins.input',side_effect=['client','test@example.com','']),patch.object(launcher.getpass,'getpass',return_value='test-secret'),patch.object(launcher,'validate_credentials',return_value=0),patch.object(launcher.subprocess,'call',return_value=0) as run,contextlib.redirect_stdout(io.StringIO()):
            launcher.main(['--local-mail'])
            self.assertEqual(run.call_args.kwargs['env']['SAVEKIN_MAIL_MODE'],'local')
