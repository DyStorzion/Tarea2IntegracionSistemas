// Genera un JWT HS256 aceptado por Kong, igual que scripts/generar_token.py.
// Secretos de DESARROLLO: deben coincidir con gateway/kong.yml.
import crypto from 'k6/crypto';
import encoding from 'k6/encoding';

const SECRETOS = {
  'cliente-demo': 'cowork-dev-secret-hs256-0123456789abcdef',
  'cliente-demo-2': 'cowork-dev-secret-hs256-cliente2-fedcba98',
};

function b64url(texto) {
  return encoding.b64encode(texto, 'rawurl');
}

export function generarToken(consumidor = 'cliente-demo', ttlSegundos = 3600) {
  const secreto = SECRETOS[consumidor];
  if (!secreto) {
    throw new Error(`consumidor desconocido: ${consumidor} (opciones: ${Object.keys(SECRETOS).join(', ')})`);
  }
  const ahora = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = b64url(JSON.stringify({ iss: consumidor, sub: consumidor, iat: ahora, exp: ahora + ttlSegundos }));
  const firma = crypto
    .hmac('sha256', secreto, `${header}.${payload}`, 'base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `${header}.${payload}.${firma}`;
}
