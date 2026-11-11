#!/usr/bin/env python3
"""Emite un JWT HS256 para el consumidor de Kong (P-01, solución provisoria).

Solo usa la librería estándar: un JWT son tres partes en base64url
(header.payload.firma) y la firma es HMAC-SHA256 de las dos primeras.

Uso:
    python3 scripts/generar_token.py                  # imprime el token
    python3 scripts/generar_token.py --sub ana --minutos 5
    JWT_SECRET=otro python3 scripts/generar_token.py

Kong identifica al consumidor por el claim `iss`, que debe coincidir con la
`key` declarada en gateway/kong.yml.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import time

SECRETO_DEV = "cowork-dev-secret-hs256-0123456789abcdef"


def b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def json_compacto(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode()


def generar_token(secreto: str, iss: str, sub: str, minutos: int) -> str:
    ahora = int(time.time())
    cabecera = {"alg": "HS256", "typ": "JWT"}
    cuerpo = {"iss": iss, "sub": sub, "iat": ahora, "exp": ahora + minutos * 60}
    firmado = f"{b64url(json_compacto(cabecera))}.{b64url(json_compacto(cuerpo))}"
    firma = hmac.new(secreto.encode(), firmado.encode(), hashlib.sha256).digest()
    return f"{firmado}.{b64url(firma)}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera un JWT HS256 para Kong")
    parser.add_argument("--iss", default="cliente-demo", help="key del consumidor en kong.yml")
    parser.add_argument("--sub", default="cliente-demo", help="identificador del cliente")
    parser.add_argument("--minutos", type=int, default=60, help="vigencia del token")
    args = parser.parse_args()
    secreto = os.environ.get("JWT_SECRET", SECRETO_DEV)
    print(generar_token(secreto, args.iss, args.sub, args.minutos))


if __name__ == "__main__":
    main()
