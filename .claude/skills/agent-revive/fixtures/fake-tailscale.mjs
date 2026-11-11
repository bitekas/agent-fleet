// A stand-in for `tailscale`, so that nothing a test runs can make anything public.
// Tests point AGENT_REVIVE_TAILSCALE at ["<node>", "<this file>"]. It answers the
// four calls share.mjs makes, keeps its funnel config in the JSON file
// $FAKE_TAILSCALE_STATE, and appends every call's arguments to <that file>.log, so a
// test can read both what is "public" and what was asked.
//   FAKE_TAILSCALE_FAIL=funnel-on    turning a funnel on exits 1 and changes nothing.
//   FAKE_TAILSCALE_FAIL=funnel-off   turning one off exits 1 and changes nothing - the
//                                    teardown that cannot finish.
// The output shapes are those of tailscale 1.104 (`status --json`, `funnel status
// --json`); only the keys share.mjs reads are reproduced.
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';

const STATE = process.env.FAKE_TAILSCALE_STATE;
if (!STATE) { console.error('fake-tailscale: FAKE_TAILSCALE_STATE is not set'); process.exit(2); }
const HOST = 'sharetest.example-tailnet.invalid';  // a real DNSName ends in the tailnet's domain; .invalid can never resolve
const args = process.argv.slice(2);
appendFileSync(`${STATE}.log`, JSON.stringify(args) + '\n');
let st;
try { st = JSON.parse(readFileSync(STATE, 'utf8')); } catch { st = { funnel: {} }; }
const save = () => writeFileSync(STATE, JSON.stringify(st));
const is = (...want) => want.length === args.length && want.every((w, i) => w === args[i]);
const https = (args.find(a => a.startsWith('--https=')) || '').slice(8);

if (is('status', '--json')) {
  console.log(JSON.stringify({ Self: { DNSName: `${HOST}.`, CapMap: { funnel: null, [`https://tailscale.com/cap/funnel-ports?ports=443,8443,10000`]: null } } }));
} else if (is('funnel', 'status', '--json')) {
  const out = {};
  for (const [port, target] of Object.entries(st.funnel)) {
    (out.TCP ??= {})[port] = { HTTPS: true };
    (out.Web ??= {})[`${HOST}:${port}`] = { Handlers: { '/': { Proxy: target } } };
    (out.AllowFunnel ??= {})[`${HOST}:${port}`] = true;
  }
  console.log(JSON.stringify(out));
} else if (args[0] === 'funnel' && args.includes('--bg') && https) {
  if (process.env.FAKE_TAILSCALE_FAIL === 'funnel-on') { console.error('fake-tailscale: funnel refused (FAKE_TAILSCALE_FAIL)'); process.exit(1); }
  st.funnel[https] = args[args.length - 1];
  save();
  console.log(`Available on the internet:\n\nhttps://${HOST}:${https}/`);
} else if (args[0] === 'funnel' && https && args[args.length - 1] === 'off') {
  if (process.env.FAKE_TAILSCALE_FAIL === 'funnel-off') { console.error('fake-tailscale: funnel off refused (FAKE_TAILSCALE_FAIL)'); process.exit(1); }
  if (!st.funnel[https]) { console.error(`error: no serve config for port ${https}`); process.exit(1); }
  delete st.funnel[https];
  save();
} else {
  console.error(`fake-tailscale: unexpected call ${JSON.stringify(args)}`);
  process.exit(2);
}
