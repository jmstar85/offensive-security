/**
 * Probe runner skeleton — reads JSON probes from stdin (one per line)
 * and emits ack results on stdout. Real Playwright probe logic lands in PR3.4.
 */
const readline = require('readline');

const rl = readline.createInterface({
  input: process.stdin,
  terminal: false,
});

rl.on('line', (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let probe;
  try {
    probe = JSON.parse(trimmed);
  } catch (e) {
    console.log(JSON.stringify({ event: 'parse_error', raw: trimmed, error: e.message }));
    return;
  }
  console.log(JSON.stringify({ event: 'probe_ack', received: probe }));
});

rl.on('close', () => {
  process.exit(0);
});
