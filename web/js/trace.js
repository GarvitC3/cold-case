import { isNum, dshort, dlong, ago, ice, num } from './fmt.js';
import { sgn, fddFmt } from './copy.js';

const SRC = { nasa: 'NASA POWER', node: 'FIELD NODE', model: 'MODEL', normal: 'NORMAL' };

export function provenance(node) {
  const sim = node.simulated;
  if (node.state === 'offline' || !node.via) return { value: 'no live reading', when: sim ? 'SIMULATED node is silent' : 'node offline — values are intentionally empty' };
  if (node.via === 'wireless') return { value: `Wi-Fi · node ‘${node.name || 'field'}’`, when: `reading arrived over Wi-Fi from node ‘${node.name || 'field'}’ ${ago(node.last_seen_age_s)}${sim ? ' · SIMULATED' : ''}` };
  return { value: sim ? 'USB · simulated' : 'USB cable', when: sim ? 'SIMULATED sensor — no hardware attached' : `reading arrived over USB${node.port ? ' (' + node.port + ')' : ''} ${ago(node.last_seen_age_s)}` };
}

export function traceSpec(kind, S) {
  const s = S.state, n = s.now, node = s.node, p = s.ice_params;
  const asOf = n.as_of ? dlong(n.as_of) : '—';
  const nodeAge = node.last_seen_age_s;
  const indoor = s.mode.deployment === 'indoor_demo';
  const pv = provenance(node);
  const linkRow = { src: 'node', label: 'Link', value: pv.value, when: pv.when };
  if (kind === 'ice') {
    return {
      title: 'Ice thickness now', src: 'model',
      formula: 'h = α · f(snow) · √FDD',
      explain: 'Stefan’s law: ice grows with the square root of accumulated freezing degree-days. Snow insulates, so it slows growth.',
      inputs: [
        { src: 'nasa', label: 'FDD verified (Nov 1 → ' + dshort(n.as_of) + ')', value: `${fddFmt(n.fdd.verified)} °C-days`, when: `NASA POWER daily T2M, as of ${asOf}` },
        { src: 'node', label: 'FDD from node since NASA’s last day', value: n.fdd.node_used ? `${fddFmt(n.fdd.node)} °C-days` : '0 (excluded)', when: indoor ? 'Indoor demo: room temperature is never counted as climate' : (n.fdd.node_used ? 'node daily means, ≥ 80% coverage' : 'no outdoor node days yet') },
        { src: 'node', label: 'Snow depth', value: n.snow.known ? `${ice(n.snow.cm)} cm` : '—', when: n.snow.known ? `ground − distance, median-filtered · ${ago(nodeAge)}` : 'no valid snow reading' },
        linkRow,
        { src: 'model', label: 'Snow factor f', value: isNum(n.ice.factor) ? n.ice.factor.toFixed(2) : '—', when: `f = ${p.snow_floor} + ${(1 - p.snow_floor).toFixed(1)}·e^(−snow/${p.snow_lambda_cm} cm)` },
        { src: 'model', label: 'Coefficient α', value: `${p.alpha} (${p.alpha_low}–${p.alpha_high})`, when: 'assumption: USACE windy lake, bare ice' },
      ],
      result: `${ice(n.ice.cm)} cm  [${ice(n.ice.lo)}–${ice(n.ice.hi)}]`,
      note: 'Estimate from a simplified model: no melt, no freeze-up delay, snow on the ground stands in for snow on the ice. Ice thickness varies across a lake. Not a safety tool. No ice is safe ice.',
      code: 'app/model.py · ice_estimate()',
      raw: 'nasa',
    };
  }
  if (kind === 'cold') {
    return {
      title: 'Cold banked this winter', src: 'nasa',
      formula: 'FDD = Σ max(0, −Tᵈᵃʸ)',
      explain: 'Freezing degree-days: how many °C below zero each day was, added up from 1 Nov.',
      inputs: [
        { src: 'nasa', label: 'Verified by NASA through ' + dshort(n.as_of), value: `${fddFmt(n.fdd.verified)} °C-days`, when: `NASA POWER daily T2M · fetched ${s.nasa.fetched_at ? dshort(s.nasa.fetched_at) : '—'}` },
        { src: 'node', label: 'Node, after NASA’s last day', value: n.fdd.node_used ? `${fddFmt(n.fdd.node)} °C-days` : 'not counted', when: indoor ? 'INDOOR DEMO — node temperature excluded' : `${n.fdd.node_days_used} full days used` },
        { src: 'normal', label: `Normal by ${dshort(n.fdd.compare_date)} (median of ${n.normal ? n.normal.n : '—'} winters)`, value: `${fddFmt(n.normal && n.normal.p50)} °C-days`, when: 'baseline from the NASA record, current winter excluded' },
      ],
      result: `${fddFmt(n.fdd.now)} °C-days banked`,
      code: 'app/fdd.py · build_winters()  ·  app/nowcast.py',
      raw: 'nasa',
    };
  }
  if (kind === 'snow') {
    return {
      title: 'Snow depth', src: 'node',
      formula: 'snow = ground − distance',
      explain: 'The ultrasonic sensor measures the distance down to whatever is below. Snow is how much closer than bare ground that surface is.',
      inputs: [
        { src: 'node', label: 'Ground level (calibrated)', value: isNum(node.snow.ground_cm) ? `${num(node.snow.ground_cm, 1)} cm` : 'not set', when: 'distance to bare ground, set with “Set ground level”' },
        { src: 'node', label: 'Distance now', value: isNum(node.dist.cm) ? `${num(node.dist.cm, 1)} cm` : '—', when: node.simulated ? 'SIMULATED sensor' : `HC-SR04, median of 5 pings · ${ago(nodeAge)}` },
        linkRow,
      ],
      result: n.snow.known ? `${ice(n.snow.cm)} cm of snow` : 'no valid reading',
      code: 'app/node.py · snow_from_dist() + SnowFilter',
    };
  }
  return {
    title: 'Air temperature', src: 'node',
    formula: 'T = DHT11 reading',
    explain: 'The prototype thermometer (DHT11) reads 0–50 °C only. Below freezing it cannot measure — a DS18B20 probe is the field fix.',
    inputs: [
      { src: 'node', label: 'Node temperature', value: node.temp.c !== null ? `${sgn(node.temp.c)} °C` : '—', when: node.temp.state === 'out_of_range' ? 'out of sensor range' : (node.simulated ? 'SIMULATED' : ago(nodeAge)) },
      linkRow,
      { src: 'nasa', label: 'NASA daily mean on ' + dshort(n.as_of), value: n.nasa_t && isNum(n.nasa_t.c) ? `${sgn(n.nasa_t.c)} °C` : '—', when: 'for comparison only' },
    ],
    result: indoor ? 'Indoor demo — not climate data' : 'Outdoor node',
    code: 'app/node.py · classify_temp()',
  };
}

export const srcLabel = (k) => SRC[k] || k;
