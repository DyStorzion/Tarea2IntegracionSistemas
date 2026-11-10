"""Genera un JWT HS256 aceptado por Kong. Solo usa la biblioteca estándar.

Uso:
    python scripts/generar_token.py              # token para cliente-1, válido 1 hora
    python scripts/generar_token.py cliente-2 --ttl 7200

Los secretos deben coincidir con gateway/kong.yml. Son valores de DESARROLLO.
"""

import argparse
import base64
import hashlib
import hmac
import json
import time

SECRETOS = {
    "cliente-1": "dev-secreto-cliente-1-cambiar",
    "cliente-2": "dev-secreto-cliente-2-cambiar",
}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generar(consumidor: str, ttl: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": consumidor, "sub": consumidor, "exp": int(time.time()) + ttl}
    firmado = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    firma = hmac.new(SECRETOS[consumidor].encode(), firmado.encode(), hashlib.sha256).digest()
    return f"{firmado}.{b64url(firma)}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera un JWT de desarrollo para Kong")
    parser.add_argument("consumidor", nargs="?", default="cliente-1", choices=sorted(SECRETOS))
    parser.add_argument("--ttl", type=int, default=3600, help="segundos de validez (por defecto 3600)")
    args = parser.parse_args()
    print(generar(args.consumidor, args.ttl))
