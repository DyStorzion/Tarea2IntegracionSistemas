// Escenario 4 · Bulkhead: Acceso tarda 1,3 s durante 60 s, menos que su timeout de 1,5 s, con 16 reservas/s.
// Las llamadas a Acceso responden a tiempo, así que el Circuit Breaker las cuenta como éxitos y no abre.
// Lo que protege es el Bulkhead: como máximo 5 llamadas simultáneas a Acceso; el exceso se rechaza al
// instante (503 ACCESO_SATURADO) y Espacios y Pagos siguen teniendo conexiones libres.
// Con RESILIENCE_ENABLED=false, Acceso ocupa todo el pool compartido y las reservas fallan en Espacios o
// Pagos aunque estén sanos: el umbral de "ninguna reserva falla en Espacios o Pagos" falla.
// Uso: docker compose run --rm k6 run /scripts/bulkhead.js
import { definirEscenario } from './lib/escenario.js';

export { setup, teardown, reservar, consultar, controlarFallas, handleSummary } from './lib/escenario.js';

const FALLAS_DE_OTRAS = ['ESPACIOS_FALLO', 'PAGOS_FALLO'];

export const options = definirEscenario({
  nombre: 'bulkhead',
  descripcion: 'Acceso tarda 1,3 s (dentro del timeout) con 16 reservas/s: el Bulkhead evita que contagie a Espacios y Pagos.',
  duracion: 100,
  reservasPorSegundo: 16, // 8 por consumidor; con las consultas quedan 9 por consumidor, bajo el límite de 10 de Kong
  consultasPorSegundo: 2,
  linea: [
    { desde: 0, fase: 'normal' },
    { desde: 20, fase: 'falla', fallas: [['acceso', 'slow', 1300]] },
    { desde: 80, fase: 'recuperacion', fallas: [['acceso', 'ok']] },
  ],
  umbrales: [
    {
      metrica: 'checks{check:ninguna reserva falla en Espacios o Pagos}',
      condicion: 'rate==1',
      etiqueta: 'durante la falla ninguna reserva falla en Espacios o Pagos (no se contagian de Acceso)',
    },
    {
      metrica: 'sagas{fase:falla,estado:CONFIRMADA}',
      condicion: 'count>0',
      etiqueta: 'durante la falla Acceso sigue confirmando reservas al ritmo que alcanza',
    },
    {
      metrica: 'checks{check:la saga termina en un estado final consistente}',
      condicion: 'rate==1',
      etiqueta: 'ninguna saga queda a medias (COMPENSACION_PENDIENTE) ni sin respuesta',
    },
    {
      metrica: 'checks{check:la consulta de disponibilidad responde 200}',
      condicion: 'rate==1',
      etiqueta: 'todas las consultas de disponibilidad responden 200',
    },
  ],
  verificar: ({ fase, error }) =>
    fase === 'falla' ? { 'ninguna reserva falla en Espacios o Pagos': !FALLAS_DE_OTRAS.includes(error) } : {},
});
