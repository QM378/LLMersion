# Running it on a remote GPU box

Nothing needs to change architecturally — the UI is already a browser talking to
an HTTP server, and the server happening to run on your laptop was incidental.
Move it to an A100 and you point the browser somewhere else.

## The recommended way: SSH tunnel

```bash
# on the server
cd linguallm
PR_NO_OPEN=1 python -m server.main          # stays on 127.0.0.1

# on your laptop
ssh -N -L 8848:127.0.0.1:8848 you@gpu-box
```

Then open `http://127.0.0.1:8848` locally. This is the recommended setup for
three reasons, one of which is easy to miss:

**Microphone scoring only works in a secure context.** `getUserMedia` is
unavailable over plain HTTP unless the origin is localhost — so browsing
directly to `http://gpu-box:8848` silently loses pronunciation scoring, while a
tunnel to `127.0.0.1` keeps it. Everything else works either way.

The other two: nothing is exposed to the network, and there is no auth to
configure because there is no open port.

Keep the tunnel alive across dropouts with `autossh -M 0 -N -L 8848:127.0.0.1:8848 you@gpu-box`.

## When port forwarding is blocked

Some clusters set `AllowTcpForwarding no`. You will see
`administratively prohibited: open failed` when the tunnel tries to open. A
terminal-only login is *not* itself a problem — the server needs no display —
but a blocked `-L` needs a different route out. In rough order of preference:

**Cloudflare Tunnel.** Outbound only, so it works from behind any firewall that
lets HTTPS out, and it terminates TLS for you — which means the microphone works,
unlike every plain-HTTP option below.

```bash
# on the server, alongside the reader
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
./cloudflared-linux-amd64 tunnel --url http://127.0.0.1:8848
```

It prints a `https://something-random.trycloudflare.com` URL. Understand what
that is: a public address on the open internet with no authentication in front
of it. **Set `PR_TOKEN` before you start the reader**, and treat the URL as a
password. Your documents and audio also transit Cloudflare's edge.

**An existing web entry point.** If the cluster runs JupyterHub or JupyterLab,
`jupyter-server-proxy` will expose a local port at
`https://hub-host/user/you/proxy/8848/` over the hub's own TLS and auth. This is
the cleanest option when it is available — someone else already solved the
authentication and the certificate.

**Ask the admins.** `AllowTcpForwarding` is usually off by inertia rather than
policy, and "I need to reach a local web UI" is a routine request.

## Login node vs compute node

On a scheduler-managed cluster the GPU is not on the machine you SSH into. Start
the reader inside your job and tunnel through the login node in one hop:

```bash
# get the compute node's name from squeue / your job output, then locally:
ssh -N -L 8848:gpu-node-07:8848 you@login-node
```

`gpu-node-07` is resolved from the login node, so it does not need to be
reachable from your laptop. Note the reader must bind `PR_HOST=0.0.0.0` on the
compute node for the login node to reach it, which means `PR_TOKEN` applies.

## Binding directly, if you must

```bash
PR_HOST=0.0.0.0 PR_TOKEN=$(openssl rand -hex 16) python -m server.main
```

The banner prints the URL with the token in it. `PR_TOKEN` is a doorstop, not
security — it is a shared secret in a query string, over cleartext HTTP. Only do
this inside a trusted network, and never on a machine with a public IP. For
anything real, put Caddy or nginx in front with a TLS certificate; that also
restores microphone support, since HTTPS is a secure context.

## What changes on an A100

**Installation gets easier.** A100 is sm_80, which every stock PyTorch build has
covered for years — no cu128/cu130 hunting. `pip install torch` is enough.

**80 GB of VRAM changes the sizing.** A 27B translation model and Kokoro and the
pronunciation model all fit at once with room to spare, so set `PR_TTS_KEEP=3`
and stop worrying about eviction. If the box is shared, keep it at 1.

**Audio crosses the network now.** A 30-second paragraph is roughly 1.4 MB of
16-bit WAV. Prefetching already runs a few paragraphs ahead so this is invisible
on a LAN, but over a slow link the first sentence of each paragraph will lag.
The cheapest fix is compressing the cache — set `PR_TTS=edge` (mp3, ~10x
smaller) or add an Opus encode step in `server/tts.py`.

**Ollama runs on the server.** `PR_OLLAMA_URL` defaults to localhost, which from
the server's point of view is correct. Nothing to change.

## What it is not built for

This is a single-user application. `data/reader.db` holds one progress row per
document, one vocabulary list, and one audio cache — two people using the same
instance will overwrite each other's position and share a word list. If you want
that, the honest fix is a `user_id` column on `progress` and `vocab` plus a way
to identify the user; the schema is small enough that it is an afternoon, but it
has not been done.

Also: uploaded documents live in `data/docs/` forever, and there is no quota, no
cleanup and no upload size limit. On a shared box, mount `PR_DATA` somewhere with
space you are willing to lose.
