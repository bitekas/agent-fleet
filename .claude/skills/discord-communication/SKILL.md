---
name: discord-communication
version: 1
description: >
  PLACEHOLDER chat transport for Discord: the chat-transport interface with
  every operation answering "not implemented in this version". Its watcher
  refuses to start, no daemon unit is rendered for it, and no install can
  enable it. Load to see what a Discord transport has to provide, or before
  implementing one; never to reach Discord.
requires_install: false
---

# Discord (placeholder)

**Not implemented in this version.** This skill is the `/chat-transport`
interface with no service behind it, so the slot exists and its shape is fixed:
`transport.json` beside this file carries `"status": "placeholder"` and the id
shapes a Discord transport will validate against, and `watch.py` refuses with
`WATCH-GUARD discord transport is a placeholder: not implemented` and exit 2.
`/slack-communication` is the working transport to model an implementation on;
`/chat-transport`, *Placeholder transports*, says what turning this into a
transport takes.

## Inbound watcher

Not implemented in this version. `watch.py [--once]` exits 2 with the line above.

## Claiming a request

The claim is `/chat-transport`'s and already names a Discord claim
(`discord--<conversation>-<message>`), but nothing delivers a Discord request
to claim.

## Post

Not implemented in this version.

## Reply in thread

Not implemented in this version.

## React

Not implemented in this version.

## Direct message

Not implemented in this version.

## Upload a file

Not implemented in this version.

## Fetch a message

Not implemented in this version.

## Permalink

Not implemented in this version.
