#!/usr/bin/env python3
"""Emite un JWT HS256 para un consumidor de Kong (P-01, solución provisoria).

Solo usa la librería estándar: un JWT son tres partes en base64url
(header.payload.firma) y la firma es HMAC-SHA256 de las dos primeras.

Uso:
    python scripts/generar_token.py                   # token para cliente-demo
    python scripts/generar_token.py cliente-demo-2    # token para el segundo consumidor
    python scripts/generar_token.py --sub ana --minutos 5
    JWT_SECRET=otro python scripts/generar_token.py   # firma con otro secreto (Kong responde 401)

Kong identifica al consumidor por el claim `iss`, que debe coincidir con la
`key` declarada en gateway/kong.yml. El secreto se elige según el consumidor;
SECRETOS debe coincidir con gateway/kong.yml y k6/lib/token.js.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import time

# Secretos de DESARROLLO, iguales a los de gateway/kong.yml.
SECRETOS = {
    "cliente-demo": "cowork-dev-secret-hs256-0123456789abcdef",
    "cliente-demo-2": "cowork-dev-secret-hs256-cliente2-fedcba98",
}
CONSUMIDOR_DEFAULT = "cliente-demo"


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
    parser.add_argument("consumidor", nargs="?", choices=sorted(SECRETOS),
                        help=f"consumidor de kong.yml (por defecto {CONSUMIDOR_DEFAULT})")
    parser.add_argument("--iss", help="key del consumidor en kong.yml (equivale al argumento consumidor)")
    parser.add_argument("--sub", help="identificador del cliente (por defecto, el consumidor)")
    parser.add_argument("--minutos", type=int, default=60, help="vigencia del token")
    args = parser.parse_args()

    if args.iss and args.consumidor and args.iss != args.consumidor:
        parser.error("indica el consumidor una sola vez (argumento o --iss)")
    iss = args.iss or args.consumidor or CONSUMIDOR_DEFAULT

    secreto = os.environ.get("JWT_SECRET") or SECRETOS.get(iss)
    if secreto is None:
        parser.error(f"consumidor desconocido {iss!r}; opciones: {', '.join(sorted(SECRETOS))}")
    print(generar_token(secreto, iss, args.sub or iss, args.minutos))


if __name__ == "__main__":
    main()
