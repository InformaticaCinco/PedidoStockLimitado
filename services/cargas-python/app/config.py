import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    port: int = 8092
    mongo_uri: str = 'mongodb://127.0.0.1:27017/?replicaSet=rs0'
    database: str = 'pedido_stock_limitado'
    jwks_url: str = 'http://pedidos-java:8090/.well-known/jwks.json'
    issuer: str = 'http://localhost:8090'
    audience: str = 'pedido-stock-limitado'
    poll_ms: int = 500
    lease_seconds: int = 30
    max_attempts: int = 3
    retry_base_ms: int = 1000
    max_upload_bytes: int = 10485760

    @classmethod
    def from_env(cls):
        names = dict(port='PORT', mongo_uri='MONGODB_URI', database='MONGODB_DATABASE',
                     jwks_url='JWT_JWKS_URL', issuer='JWT_ISSUER', audience='JWT_AUDIENCE',
                     poll_ms='QUEUE_POLL_MS', lease_seconds='QUEUE_LEASE_SECONDS',
                     max_attempts='QUEUE_MAX_ATTEMPTS', retry_base_ms='QUEUE_RETRY_BASE_MS',
                     max_upload_bytes='MAX_UPLOAD_BYTES')
        defaults = cls()
        values = {}
        for key, name in names.items():
            default = getattr(defaults, key)
            value = os.environ.get(name, default)
            values[key] = int(value) if isinstance(default, int) else value
            if not values[key] or isinstance(values[key], int) and values[key] < 1:
                raise ValueError(f'Configuración inválida: {name}')
        if values['port'] > 65535:
            raise ValueError('PORT inválido')
        return cls(**values)
