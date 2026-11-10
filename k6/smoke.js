// Prueba de humo del gateway: autenticación y enrutamiento.
// Uso: docker compose run --rm k6 run /scripts/smoke.js
import http from 'k6/http';
import { check } from 'k6';
import { generarToken } from './lib/token.js';

const BASE_URL = __ENV.BASE_URL || 'http://gateway:8000';

export const options = { vus: 1, iterations: 1 };

export default function () {
  const sinToken = http.get(`${BASE_URL}/api/espacios`);
  check(sinToken, { 'sin token -> 401': (r) => r.status === 401 });

  const auth = { headers: { Authorization: `Bearer ${generarToken('cliente-1')}` } };
  const conToken = http.get(`${BASE_URL}/api/espacios`, auth);
  // Mientras Espacios no esté implementado responde 501; lo importante es que el gateway dejó pasar la petición.
  check(conToken, { 'con token -> llega al servicio (no 401)': (r) => r.status !== 401 && r.status !== 404 });
}
