// Piezas comunes de los escenarios de falla: carga de reservas, consultas de disponibilidad,
// inyección de fallas según una línea de tiempo y el resumen que se guarda en /resultados.
//
// Cada script define su escenario con definirEscenario({...}) y reexporta las funciones de aquí:
//
//   export const options = definirEscenario({ nombre, duracion, linea, reservasPorSegundo, ... });
//   export { setup, teardown, reservar, consultar, controlarFallas, handleSummary } from './lib/escenario.js';
import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { generarToken } from './token.js';

const BASE_URL = __ENV.BASE_URL || 'http://kong:8000';
const CONSUMIDORES = ['cliente-demo', 'cliente-demo-2']; // la carga se alterna: Kong limita a 10 req/s por consumidor
const ESPACIOS = ['PUESTO-01', 'PUESTO-02', 'PUESTO-03', 'SALA-A', 'SALA-B'];
const BLOQUES = 12; // 8 a 19
const GRACIA_S = 2; // segundos tras cada cambio de fase que se marcan como "transicion"
const ESTADOS = ['CONFIRMADA', 'COMPENSADA', 'RECHAZADA', 'COMPENSACION_PENDIENTE', 'SIN_RESPUESTA'];
const ESTADOS_FINALES = ['CONFIRMADA', 'COMPENSADA', 'RECHAZADA'];
const ERRORES = [
  'ESPACIO_NO_EXISTE', 'FRANJA_OCUPADA', 'FRANJA_PASADA', 'PAGO_RECHAZADO', 'ESPACIOS_FALLO', 'PAGOS_FALLO',
  'ACCESO_FALLO', 'ACCESO_NO_DISPONIBLE', 'ACCESO_SATURADO', 'COMPENSACION_FALLIDA',
];
// Las franjas de prueba parten en el año 2100 y cada corrida empieza en un punto al azar de un rango de
// ~200 años: no chocan con reservas hechas a mano ni con las de otras corridas.
const PRIMER_DIA = Date.UTC(2100, 0, 1);
const RANGO_FRANJAS = 4000000;

// Código HTTP que corresponde a cada estado final de la saga.
const CODIGOS_POR_ESTADO = {
  CONFIRMADA: [200, 201],
  RECHAZADA: [200, 404, 409, 422, 503],
  COMPENSADA: [200, 402, 502, 503],
  COMPENSACION_PENDIENTE: [200, 502],
};

const SAGAS = new Counter('sagas'); // una por reserva, etiquetada con su fase, estado y código de error

let config = null;
const TOKENS = {};
for (const c of CONSUMIDORES) TOKENS[c] = generarToken(c, 7200);

// ------------------------------------------------------------------ Definición
export function definirEscenario(c) {
  config = c;
  const fases = [...new Set(c.linea.map((p) => p.fase)), 'transicion'];
  const scenarios = {
    reservas: {
      executor: 'constant-arrival-rate',
      exec: 'reservar',
      rate: c.reservasPorSegundo,
      timeUnit: '1s',
      duration: `${c.duracion}s`,
      preAllocatedVUs: c.reservasPorSegundo * 5,
      maxVUs: c.reservasPorSegundo * 15, // sin los patrones una saga puede tardar varios segundos
    },
    fallas: {
      executor: 'per-vu-iterations',
      exec: 'controlarFallas',
      vus: 1,
      iterations: 1,
      maxDuration: `${c.duracion + 30}s`,
    },
  };
  if (c.consultasPorSegundo) {
    scenarios.consultas = {
      executor: 'constant-arrival-rate',
      exec: 'consultar',
      rate: c.consultasPorSegundo,
      timeUnit: '1s',
      duration: `${c.duracion}s`,
      preAllocatedVUs: 5,
      maxVUs: 50,
    };
  }

  const thresholds = {};
  const agregar = (metrica, condicion) => {
    thresholds[metrica] = (thresholds[metrica] || []).concat(condicion);
  };
  for (const u of c.umbrales) agregar(u.metrica, u.condicion);
  // Submétricas informativas: siempre pasan; sirven para que el resumen traiga los conteos y latencias por fase.
  for (const f of fases) {
    agregar(`http_req_duration{escenario:reserva,fase:${f}}`, 'p(95)>=0');
    if (c.consultasPorSegundo) agregar(`http_req_duration{escenario:consulta,fase:${f}}`, 'p(95)>=0');
    for (const e of ESTADOS) agregar(`sagas{fase:${f},estado:${e}}`, 'count>=0');
    for (const e of ERRORES) agregar(`sagas{fase:${f},error:${e}}`, 'count>=0');
  }
  return { scenarios, thresholds, summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'max'] };
}

// ------------------------------------------------------------------ Ciclo de vida
export function setup() {
  const salud = http.get('http://reservas:8000/health', { tags: { escenario: 'control' } });
  let patrones = 'desconocido';
  try {
    patrones = salud.json('resilience_enabled') ? 'con-patrones' : 'sin-patrones';
  } catch (e) {
    console.warn('no se pudo leer /health de reservas');
  }
  for (const svc of ['acceso', 'pagos']) chaos(svc, 'ok');
  return {
    inicio: Date.now(),
    corrida: Math.random().toString(16).slice(2, 10),
    desplazamiento: Math.floor(Math.random() * RANGO_FRANJAS), // franjas distintas en cada corrida
    patrones,
    linea: config.linea,
  };
}

export function teardown() {
  for (const svc of ['acceso', 'pagos']) chaos(svc, 'ok');
}

export function controlarFallas(data) {
  for (const p of data.linea) {
    const espera = (data.inicio + p.desde * 1000 - Date.now()) / 1000;
    if (espera > 0) sleep(espera);
    for (const [svc, modo, delay] of p.fallas || []) chaos(svc, modo, delay);
    console.log(`[${p.desde}s] fase ${p.fase}${(p.fallas || []).map(([s, m, d]) => ` · ${s} ${m}${d ? ` ${d} ms` : ''}`).join('')}`);
  }
}

function chaos(svc, modo, delayMs = 0) {
  const r = http.post(`http://${svc}:8000/admin/chaos`, JSON.stringify({ modo, delay_ms: delayMs }), {
    headers: { 'Content-Type': 'application/json' },
    tags: { escenario: 'control' },
  });
  if (r.status !== 200) console.error(`no se pudo poner ${svc} en modo ${modo}: HTTP ${r.status}`);
}

export function faseActual(data) {
  const t = (Date.now() - data.inicio) / 1000;
  let actual = data.linea[0];
  for (const p of data.linea) if (t >= p.desde) actual = p;
  return actual.desde > 0 && t - actual.desde < GRACIA_S ? 'transicion' : actual.fase;
}

// ------------------------------------------------------------------ Carga
export function reservar(data) {
  const i = exec.scenario.iterationInTest;
  const fase = faseActual(data);
  const franja = data.desplazamiento + i; // cada reserva pide una franja distinta: ninguna choca con otra
  const fecha = new Date(PRIMER_DIA + Math.floor(franja / (ESPACIOS.length * BLOQUES)) * 86400000)
    .toISOString()
    .slice(0, 10);
  const cuerpo = {
    espacio_id: ESPACIOS[franja % ESPACIOS.length],
    fecha,
    bloque: 8 + (Math.floor(franja / ESPACIOS.length) % BLOQUES),
  };
  const consumidor = CONSUMIDORES[i % CONSUMIDORES.length];
  const r = http.post(`${BASE_URL}/api/reservas`, JSON.stringify(cuerpo), {
    headers: {
      Authorization: `Bearer ${TOKENS[consumidor]}`,
      'Content-Type': 'application/json',
      'Idempotency-Key': `${data.corrida}-${i}`,
    },
    tags: { escenario: 'reserva', fase },
    timeout: '40s',
  });

  let saga = null;
  try {
    saga = r.json();
  } catch (e) {
    saga = null;
  }
  const estado = saga && saga.estado ? saga.estado : 'SIN_RESPUESTA';
  const error = saga && saga.error ? saga.error.codigo : '';
  SAGAS.add(1, { fase, estado, error });

  const comunes = {
    'la saga termina en un estado final consistente': () => ESTADOS_FINALES.includes(estado),
    'el código HTTP corresponde al estado de la saga': () => (CODIGOS_POR_ESTADO[estado] || []).includes(r.status),
  };
  const propias = config.verificar ? config.verificar({ fase, estado, error, status: r.status, duracion: r.timings.duration }) : {};
  const reglas = { ...comunes };
  for (const [nombre, ok] of Object.entries(propias)) reglas[nombre] = () => ok;
  check(r, reglas, { fase });
}

export function consultar(data) {
  const fase = faseActual(data);
  const consumidor = CONSUMIDORES[exec.scenario.iterationInTest % CONSUMIDORES.length];
  const r = http.get(`${BASE_URL}/api/espacios?fecha=2100-01-01`, {
    headers: { Authorization: `Bearer ${TOKENS[consumidor]}` },
    tags: { escenario: 'consulta', fase },
  });
  check(r, { 'la consulta de disponibilidad responde 200': (x) => x.status === 200 }, { fase });
}

// ------------------------------------------------------------------ Resumen
export function handleSummary(data) {
  const ctx = data.setup_data || {};
  const fecha = new Date().toISOString().slice(0, 19).replace('T', ' ');
  const archivo = `${config.nombre}-${ctx.patrones || 'desconocido'}-${fecha.replace(/[: ]/g, '-')}`;
  const texto = informe(data, ctx, fecha);
  const json = {
    escenario: config.nombre,
    descripcion: config.descripcion,
    fecha,
    patrones: ctx.patrones,
    linea: config.linea,
    umbrales: config.umbrales.map((u) => ({ ...u, ok: umbralOk(data, u), valor: valorUmbral(data, u) })),
    sagas: tablaSagas(data),
    errores: tablaErrores(data),
    latencias: tablaLatencias(data),
    checks: checksPorNombre(data),
    metricas: data.metrics,
  };
  return {
    stdout: texto,
    [`/resultados/${archivo}.txt`]: texto,
    [`/resultados/${archivo}.json`]: JSON.stringify(json, null, 2),
  };
}

function fasesUsadas() {
  return [...new Set(config.linea.map((p) => p.fase)), 'transicion'];
}

function umbralOk(data, u) {
  const m = data.metrics[u.metrica];
  return m && m.thresholds ? Object.values(m.thresholds).every((t) => t.ok) : false;
}

function valorUmbral(data, u) {
  const m = data.metrics[u.metrica];
  if (!m) return null;
  const clave = u.condicion.split(/[<>=!]/)[0];
  return m.values[clave] !== undefined ? m.values[clave] : null;
}

function conteo(data, metrica) {
  const m = data.metrics[metrica];
  return m ? m.values.count : 0;
}

function tablaSagas(data) {
  const t = {};
  for (const f of fasesUsadas()) {
    const fila = {};
    for (const e of ESTADOS) fila[e] = conteo(data, `sagas{fase:${f},estado:${e}}`);
    if (Object.values(fila).some((n) => n > 0)) t[f] = fila;
  }
  return t;
}

function tablaErrores(data) {
  const t = {};
  for (const f of fasesUsadas()) {
    for (const e of ERRORES) {
      const n = conteo(data, `sagas{fase:${f},error:${e}}`);
      if (n > 0) (t[f] = t[f] || {})[e] = n;
    }
  }
  return t;
}

function tablaLatencias(data) {
  const t = {};
  for (const tipo of ['reserva', 'consulta']) {
    for (const f of fasesUsadas()) {
      const m = data.metrics[`http_req_duration{escenario:${tipo},fase:${f}}`];
      if (m && m.values.max > 0) t[`${tipo} · ${f}`] = { p50: m.values['p(50)'], p95: m.values['p(95)'], max: m.values.max };
    }
  }
  return t;
}

function checksPorNombre(data) {
  const lista = [];
  const recorrer = (g) => {
    for (const c of g.checks || []) lista.push({ nombre: c.name, pasan: c.passes, fallan: c.fails });
    for (const sub of g.groups || []) recorrer(sub);
  };
  recorrer(data.root_group);
  return lista;
}

function ms(v) {
  return v === null || v === undefined ? '-' : `${Math.round(v)} ms`;
}

function informe(data, ctx, fecha) {
  const l = [];
  l.push(`Escenario ${config.nombre} · ${ctx.patrones || 'patrones: desconocido'} · ${fecha} UTC`);
  l.push(config.descripcion);
  l.push('');
  l.push('Línea de tiempo:');
  for (const p of config.linea) {
    const fallas = (p.fallas || []).map(([s, m, d]) => `${s} ${m}${d ? ` ${d} ms` : ''}`).join(', ');
    l.push(`  ${String(p.desde).padStart(4)} s  ${p.fase.padEnd(13)} ${fallas}`);
  }
  l.push(`  ${String(config.duracion).padStart(4)} s  fin`);
  l.push('');
  l.push('Umbrales (lo que el patrón debe garantizar):');
  for (const u of config.umbrales) {
    const v = valorUmbral(data, u);
    const valor = v === null ? '' : u.condicion.startsWith('p(') ? ` · medido ${ms(v)}` : ` · medido ${Math.round(v * 1000) / 1000}`;
    l.push(`  ${umbralOk(data, u) ? '✓' : '✗'} ${u.etiqueta}${valor}`);
  }
  l.push('');
  l.push('Sagas por fase y estado:');
  const sagas = tablaSagas(data);
  const cortos = { COMPENSACION_PENDIENTE: 'PENDIENTE', SIN_RESPUESTA: 'SIN RESPUESTA' };
  l.push(`  ${'fase'.padEnd(13)}${ESTADOS.map((e) => (cortos[e] || e).padStart(14)).join('')}`);
  for (const [f, fila] of Object.entries(sagas)) l.push(`  ${f.padEnd(13)}${ESTADOS.map((e) => String(fila[e]).padStart(14)).join('')}`);
  const errores = tablaErrores(data);
  if (Object.keys(errores).length) {
    l.push('');
    l.push('Motivo de las sagas no confirmadas:');
    for (const [f, fila] of Object.entries(errores)) {
      l.push(`  ${f.padEnd(13)}${Object.entries(fila).map(([e, n]) => `${e} ${n}`).join(' · ')}`);
    }
  }
  l.push('');
  l.push('Latencias vistas por el cliente:');
  for (const [k, v] of Object.entries(tablaLatencias(data))) l.push(`  ${k.padEnd(26)} p50 ${ms(v.p50).padStart(8)}   p95 ${ms(v.p95).padStart(8)}   máx ${ms(v.max).padStart(8)}`);
  l.push('');
  l.push('Verificaciones:');
  for (const c of checksPorNombre(data)) l.push(`  ${c.fallan === 0 ? '✓' : '✗'} ${c.nombre}: ${c.pasan} pasan, ${c.fallan} fallan`);
  l.push('');
  return l.join('\n');
}
