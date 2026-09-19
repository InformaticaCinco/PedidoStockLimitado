import asyncio
import time
import jwt


class AuthError(Exception):
    def __init__(self, status=401):
        self.status = status


class Jwks:
    def __init__(self, settings, http):
        self.settings, self.http = settings, http
        self.keys, self.loaded = {}, 0.0
        self.lock = asyncio.Lock()

    async def fetch(self):
        response = await self.http.get(self.settings.jwks_url)
        response.raise_for_status()
        body = response.json()
        if body.get('code') != 200:
            raise ValueError('JWKS_INVALIDO')
        keys = {}
        for key in body['data']['keys']:
            if key.get('kty') == 'RSA' and key.get('alg') == 'RS256' and key.get('use') == 'sig' and key.get('kid'):
                if 'd' in key or key['kid'] in keys:
                    raise ValueError('JWKS_INVALIDO')
                keys[key['kid']] = jwt.PyJWK.from_dict(key).key
        if not keys:
            raise ValueError('JWKS_VACIO')
        return keys

    async def authenticate(self, authorization):
        try:
            if not authorization or not authorization.startswith('Bearer '):
                raise AuthError()
            token = authorization[7:]
            if len(token) > 16384:
                raise AuthError()
            header = jwt.get_unverified_header(token)
            kid = header.get('kid')
            if header.get('alg') != 'RS256' or not isinstance(kid, str):
                raise AuthError()
            async with self.lock:
                if time.monotonic() - self.loaded > 300 or kid not in self.keys:
                    self.keys = await self.fetch()
                    self.loaded = time.monotonic()
            key = self.keys.get(kid)
            if key is None:
                raise AuthError()
            claims = jwt.decode(token, key, algorithms=['RS256'], issuer=self.settings.issuer,
                                audience=self.settings.audience, options={'require': ['exp', 'iss', 'aud', 'sub', 'rol']})
            if not isinstance(claims['sub'], str) or not claims['sub'] or not isinstance(claims['rol'], str):
                raise AuthError()
        except AuthError:
            raise
        except Exception as exc:
            raise AuthError() from exc
        if claims['rol'] != 'ADMIN':
            raise AuthError(403)
        return claims['sub']
