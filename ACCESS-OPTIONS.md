# Browser access

## Supported attachment path

Version 0.2.1 was verified with a regular Chrome instance using a dedicated
profile and a loopback CDP endpoint. Start Chrome and sign in manually before
running Cookbook Shelf, then leave the browser open. See the README for setup.

Each operation creates its own temporary query tab, reads bounded Bookshelf
results, closes that tab, and disconnects. The browser and sign-in tab stay open.
Session credentials remain in the dedicated local browser profile.

Only explicit loopback IP addresses with a port are accepted for `EYB_CDP_URL`.
Keep the debugging endpoint local and use the dedicated browser only for EYB.
An authenticated session does not guarantee that future requests will be accepted.
Verification challenges and rate limits are reported as errors rather than retried
indefinitely. See [VALIDATION.md](VALIDATION.md) for tested behavior and limits.

## Original launcher mode

Without `EYB_CDP_URL`, the tool starts a browser with its own persistent profile.
Two live attempts with this mode stalled at Cloudflare verification. Enabling
Chromium sandboxing corrected a launch setting but did not resolve the challenge.
The original launcher remains available, but attachment is the verified path.

Cloudflare documents automated-browser limitations in its
[supported-browser reference](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/).

## Other approaches

A browser extension or an importer for user-saved pages could be explored in the
future. Neither is implemented. An importer would search only the saved content;
it would not establish a complete index of all recipes in the physical collection.

Authentication and access rights are separate concerns. Review the README's
access-terms section before use.
