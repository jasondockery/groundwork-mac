---
name: x-posting
description: Drafts X (x.com, Twitter) posts and threads as copy-ready text the owner pastes into the X app, and publishes through the official xurl CLI only when they explicitly ask and approve each write. Use when asked to announce a release, share a project update, write a post or thread, reply, quote, or otherwise act on X. Not for reading or monitoring X without a posting goal, not for other social networks, and never for browser automation of x.com.
---

# X posting

A thin wrapper around the official xurl agent skill. xurl's own SKILL.md is the
command reference; this skill adds draft-only output by default, the approval and
cost rules for publishing, and the writing guidance.

- Upstream: `xdevplatform/xurl` SKILL.md at tag **v1.3.4**, commit
  `18dcb447f090667171ff23666a05d6d387e2aa73`, MIT License.
  SKILL.md sha256 `19312e9561bb9a82e1af7823e52e4cb352dd2a0e2190dfc14744d573a075f4f3`.
- Use only that upstream (no forks). Prefer the pinned release archive and
  `xurl_1.3.4_checksums.txt`; the npm launcher skips checksum verification.

## Hard rules

1. **Draft only, by default.** The default output is copy-ready text the
   owner pastes into the X app, at no API cost. Publish through xurl only
   when they explicitly ask ("post it", "publish this", "send the thread").
   Never offer to publish, or nudge toward it, beyond one short line saying
   they can ask.
2. **Every write needs explicit approval first**, and the approval prompt
   shows the cost estimate first (see Cost). Writes include any `xurl`
   invocation that posts, mutates, or sends; `xurl chat read` and `xurl
   chat listen` (they mark messages read unless `--no-mark-read` is
   passed); any raw `xurl -X POST|PUT|PATCH|DELETE` or `-d` body; and
   every `xurl auth` subcommand except the exact argv `xurl auth status`.
   This list is not exhaustive. Approval covers the exact text shown, not
   later edits.
3. **Secrets never enter the session.** Never read anything under
   `~/.xurl/`. Never use `--verbose`/`-v` or `--pin`. Never run
   `xurl token` or `xurl mcp`. Never pass `--bearer-token`,
   `--consumer-key`, `--consumer-secret`, `--access-token`,
   `--token-secret`, `--client-id`, or `--client-secret`. Never ask the
   owner to paste a credential. Never put a token on argv. App
   registration, `xurl auth oauth2`, `xurl auth oauth1`, `xurl auth app-only`,
   and `xurl chat keys restore`/`import` are run by the owner.
4. **No location, host, workplace, or private details** in any post, alt
   text, or media.
5. **Publish only through xurl** on the owner's own machine. Do not drive a
   browser on x.com, and do not use another X integration to publish
   unless the owner approves that path. Do not use browser-automation
   posting skills; they drive a signed-in browser profile.

The harness should enforce rules 2 and 3 as well. Allow only the exact
argv `xurl auth status` with no extra flags. Ask before every other xurl
invocation. Deny `~/.xurl`, `xurl token`, `xurl mcp`, `--verbose`/`-v`,
`--pin`, `--bearer-token`, `--consumer-key`, `--consumer-secret`,
`--access-token`, `--token-secret`, `--client-id`, and `--client-secret`.
Do not wrap xurl; wrappers may miss these rules.

## Default: copy-ready draft

For a single post, give the text in one code block, then its weighted
character count (CJK and many emoji count as 2 under twitter-text
weighting). For a thread, put each post in its own code block so it
can be copied alone. The number (`1/3`) is part of the post text and is
counted; the label line above each block is not part of the post:

    Post 1/3 (first post, 212/280)
    ```
    1/3 Compass now ships shared agent skills ...
    ```

Keep every post within 280 weighted characters. Then list any media with
alt text. xurl v1.3.4 cannot attach alt text; do not xurl-publish media
that needs it — tell the owner to post that one in the X app. End with
at most one line such as "Say 'post it' if you want me to publish this
through xurl." Nothing else about publishing.

## Publishing (only on explicit request)

1. Before any write, check `xurl version` (the harness will ask; that is
   expected). Stop unless it is `xurl 1.3.4`.
2. Readiness without secrets: `xurl auth status` (read-only, no extra
   flags, no approval). When several oauth2 users are listed, confirm
   identity against the default `▸ oauth2:` line. Skip billed `xurl
   whoami` (~$0.010) unless that username is missing; include it in the
   cost estimate, run only after approval, keep only `data.username`/`data.id`.
3. Show the approval prompt: cost estimate first, then the exact final
   text of every post in order. Wait for an explicit yes.
4. Publish with approved text as one argv using shell-safe single quotes
   (`'` becomes `'\''`). Never interpolate draft text into double quotes.
   - Single post: `xurl post 'TEXT'`.
   - Media that needs no alt text: `xurl media upload 'FILE'` (same `'`
     → `'\''` encoding), read `Media ID:` (or `data.id`), then `xurl post 'TEXT' --media-id ID`.
   - Thread: post 1, read `data.id`, then `xurl reply <id> 'NEXT'` to
     each later post, always replying to the post just created.
5. After each command, check the exit code and JSON. On error, stop,
   report published vs not (with links), and ask before retrying. Never
   retry blindly: a timeout may still have posted. Report final links
   (`https://x.com/<handle>/status/<id>`).

## Writing

- Hook first: the first post must stand alone in a timeline.
- Up to 280 weighted characters per post; every URL counts as 23. If they
  may publish via xurl, put the link in one post only, usually the last.
- Plain language, no hashtag stuffing, no engagement bait.
- AI-help disclosure is **off by default**. Turn it on per post when the
  owner asks ("disclose this one"), or per repo with the setting below.
  When on, put it in the draft so it is reviewed and counted. Never
  append it after approval or on your own.

## Settings

Consuming repos may set `x-posting: disclose-ai = on` in AGENTS.md
(default off). When on, the last post includes "Drafted with AI help."
before review; the owner can remove it from any single draft.

## Cost

Show an estimate before asking approval. Example (prices 2026-10-23):
`2 x $0.015 + 1 x $0.200 (URL) = $0.230. Publish? (yes/no)`. Rates from
https://docs.x.com/x-api/getting-started/pricing: $0.015 Post: Create,
$0.200 with a URL. List other writes from that page or omit them. Drafts cost nothing.

## Alternatives

Use Typefully or another queue only if the owner wants scheduling or a
shared draft queue; the same secret and approval rules apply.

## License

This skill adapts material from xurl's SKILL.md.

```
MIT License

Copyright (c) 2024 Santiago Medina Rolong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
