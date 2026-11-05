import base64
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

try:
    from fastapi.testclient import TestClient
    from aether.interfaces.api.app import create_app
except ImportError:
    TestClient = None
    create_app = None


class _ProviderResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeOAuthProvider:
    calls = []

    def __init__(self, *, timeout):
        self.timeout = timeout
        self.calls = []
        type(self).calls = self.calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, json):
        self.calls.append((url, json))
        if url.endswith('/ExchangeToken'):
            return _ProviderResponse({'accessToken': 'provider-access-fixture-not-a-secret'})
        if url.endswith('/GetUserInfo'):
            return _ProviderResponse({'openId': 'oauth-owner-fixture', 'name': 'Test Operator'})
        raise AssertionError(f'unexpected Manus OAuth endpoint: {url}')


@unittest.skipIf(TestClient is None, 'API dependencies are not installed')
class ManusOAuthWireContractTests(unittest.TestCase):
    def test_platform_urls_state_exchange_identity_and_session_redirect(self):
        environment = {
            'MANUS_PROJECT_ID': 'project-fixture',
            'MANUS_OAUTH_PORTAL_URL': 'https://portal.example/base/',
            'MANUS_OAUTH_API_URL': 'https://api.example/root/',
            'AETHER_OPERATOR_OPEN_IDS': 'oauth-owner-fixture',
        }
        with patch.dict(os.environ, environment, clear=False), tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode='manus', public_origin='https://preview.example')
            with TestClient(app, base_url='https://preview.example', follow_redirects=False) as browser:
                info = browser.get('/api/v1/auth/info')
                self.assertTrue(info.json()['login_available'])
                started = browser.get('/api/v1/auth/login-url')
                self.assertEqual(started.status_code, 200)
                location = urlparse(started.json()['url'])
                self.assertEqual(location.scheme + '://' + location.netloc + location.path, 'https://portal.example/base/app-auth')
                params = parse_qs(location.query)
                redirect_uri = 'https://preview.example/api/v1/auth/callback'
                self.assertEqual(params['appId'], ['project-fixture'])
                self.assertEqual(params['redirectUri'], [redirect_uri])
                self.assertEqual(params['responseType'], ['code'])
                state = params['state'][0]
                state_data = json.loads(base64.b64decode(state))
                self.assertEqual(state_data['redirectUri'], redirect_uri)
                self.assertTrue(state_data['nonce'])
                self.assertEqual(browser.cookies.get('aether_oauth_state').strip('"'), state)

                with patch('aether.interfaces.api.services.auth.httpx.AsyncClient', _FakeOAuthProvider):
                    callback = browser.get('/api/v1/auth/callback', params={'code': 'temporary-code', 'state': state})
                self.assertEqual(callback.status_code, 303)
                self.assertEqual(callback.headers['location'], '/')
                cookies = callback.headers.get_list('set-cookie')
                session_cookie = next(value for value in cookies if value.startswith('webdev_app_session='))
                self.assertIn('httponly', session_cookie.lower())
                self.assertIn('secure', session_cookie.lower())
                self.assertIn('samesite=none', session_cookie.lower())
                session = browser.get('/api/v1/auth/session')
                self.assertEqual(session.status_code, 200)
                self.assertEqual(session.json()['open_id'], 'oauth-owner-fixture')
                self.assertEqual(session.json()['role'], 'operator')
                self.assertEqual([call[0] for call in _FakeOAuthProvider.calls], [
                    'https://api.example/root/webdev.v1.WebDevAuthPublicService/ExchangeToken',
                    'https://api.example/root/webdev.v1.WebDevAuthPublicService/GetUserInfo',
                ])
                self.assertEqual(
                    _FakeOAuthProvider.calls[0][1],
                    {'clientId': 'project-fixture', 'grantType': 'authorization_code', 'code': 'temporary-code', 'redirectUri': redirect_uri},
                )
                self.assertEqual(_FakeOAuthProvider.calls[1][1], {'accessToken': 'provider-access-fixture-not-a-secret'})

                reused = browser.get('/api/v1/auth/callback', params={'code': 'replay-code', 'state': state})
                self.assertEqual(reused.status_code, 400)


if __name__ == '__main__':
    unittest.main()
