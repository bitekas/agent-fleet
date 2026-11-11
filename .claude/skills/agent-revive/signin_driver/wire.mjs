// The driver's output path, and the code file - both pure, both dependency-free, so
// `redaction.test.mjs` can exercise them without a browser.
//
// ⚠️ EVERY BYTE THE DRIVER SENDS TO A CLIENT LEAVES THROUGH `replyLine`, AND THAT IS
// THE WHOLE SECURITY ARGUMENT. The driver holds an agent's Google password in memory
// (it types it into the password field so no human and no transcript ever has to
// carry it) and it sees the OAuth code on the callback page. Neither may come back
// out. Funnelling every reply through one function means a new command added to the
// driver's switch is redacted by DEFAULT; redacting at each call site would make the
// next command unredacted by default, and nothing would go red.
//
// ⚠️ THE ERROR PATH IS THE ONE THAT LEAKS. A successful reply is a small object the
// author chose; a thrown Playwright error quotes the ARGUMENT it failed on - which,
// for the fill that types the password, IS the password. So the catch branch goes
// through the same redactor, and `redaction.test.mjs` pins it with a throwing
// handler rather than only with a returning one.

import { writeFileSync, chmodSync } from 'node:fs';
import { extractCode } from './redact.mjs';

/**
 * Turn one inbound JSON line into the exact string written back to the socket.
 * `handle` is the driver's command dispatcher; `redact` comes from makeRedactor.
 * Returns a newline-terminated string. Never throws.
 */
export async function replyLine(line, handle, redact) {
  let reply;
  try {
    const cmd = JSON.parse(line);
    const r = await handle(cmd);
    reply = { ok: true, result: Array.isArray(r) ? await Promise.all(r) : r };
  } catch (e) {
    reply = { ok: false, error: String(e && e.message ? e.message : e).split('\n')[0] };
  }
  return redact(JSON.stringify(reply)) + '\n';
}

/**
 * Write the OAuth code found in `text` to `path`, mode 0600.
 *
 * ⚠️ THE RETURN VALUE DELIBERATELY DOES NOT CONTAIN THE CODE, and `length` is what
 * replaces it. The reviving agent needs to know a code was captured and that it is
 * whole; it does not need the characters, and the characters are what would end up
 * in a tool result, a transcript and a session log that outlives the revival. The
 * agent pastes with `tmux send-keys -l -- "$(cat <file>)"`, which moves the code
 * from the file to the pane without it passing through anything that records.
 *
 * ⚠️ A code that is written and not pasted is worthless within about a minute
 * (SKILL.md step 6). This function is therefore the signal to paste NOW, not a
 * place to park a code for later.
 */
export function saveCodeFile(text, path) {
  const code = extractCode(text);
  if (!code) return { saved: false };
  writeFileSync(path, code);
  chmodSync(path, 0o600);
  return { saved: true, file: path, length: code.length };
}
