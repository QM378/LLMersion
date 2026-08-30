# Voice packs

One folder per voice. Any cloning-capable engine (currently Chatterbox) will
offer every pack in the dropdown.

Packs live under the per-user data directory the startup banner prints, in
`models/voices/`:

```
<data-dir>/models/voices/
  ny_male_carl/
    reference.wav      # 6–20 s, one speaker, clean, no music
    voice.json         # optional metadata
```

`voice.json` (or `voice.toml`):

```json
{
  "label": "Carl — Queens, NY",
  "accent": "New York",
  "gender": "male",
  "engines": ["chatterbox"],
  "ref_text": "transcript of the clip, only some engines need it",
  "params": { "exaggeration": 0.45, "cfg": 0.5 }
}
```

Then hit **重新扫描** in the 语音 panel — no restart needed. Because they sit
outside the project, packs survive replacing the code.

## Where to get accent recordings

There is no downloadable "Chicago male" TTS checkpoint. Regional accents come
from handing a cloning model a reference clip, so what you need is *audio*, not
weights. Sources that are legally clean:

| source | licence | notes |
|---|---|---|
| LibriVox | public domain | volunteer audiobook readers, many strong US regional accents; pick a reader and clip 15 s |
| Mozilla Common Voice | CC0 | has self-reported accent metadata; clips are short, so concatenate a few from one speaker |
| Library of Congress, *American English Dialect Recordings* | public domain | field recordings, exactly the regional coverage you want, but older audio quality |
| CORAAL | open, with citation | Corpus of Regional African American Language |
| your own microphone | yours | the most reliable option, and the only one with zero ambiguity |

Do not clone a specific real person's voice without their consent — a public
figure's voice is not fair game just because a recording is easy to find. The
sources above are either explicitly released for reuse or old enough to be
public domain, and generic regional speech is what you want anyway.

## Getting a good clip

* 6–20 seconds. Longer is not better; the model only needs timbre and prosody.
* One speaker, no music, no reverb, no phone-line compression.
* Normal reading pace and neutral emotion — the clip's mood carries into every
  sentence the model speaks.
* Mono WAV, 16 kHz or higher. `ffmpeg -i in.mp3 -ac 1 -ar 24000 -t 15 reference.wav`
