# The steering video

An animatic: one still frame per moment, held while its one spoken line plays.
It tells the owner what changes for a user and in the codebase, in the grill's
words, in build order, so they can steer by watching. It never shows a bench or
the ticket graph.

`storyboard.json` is an array of moments, in playback order:

```json
[
  {"say": "Widget export. Here's what changes, in the order we'll build it.",
   "frame": {"type": "title", "kicker": "Spec 9100", "headline": "Widget export", "sub": "From the confirmed grill"}},
  {"say": "First, one versioned export contract, that everything else writes.",
   "frame": {"type": "codebase", "step": 1, "headline": "One export contract, first", "paths": ["contracts/export.v1.md"]}},
  {"say": "Then you get an export button, that saves every widget to one file.",
   "frame": {"type": "user", "step": 2, "headline": "An export button", "points": ["Saves every widget", "One file"]}}
]
```

- **`title`** opens the video, once: `headline`, optional `kicker` and `sub`.
- **`user`**: a change the user sees: `step`, `headline`, `points` (1 to 4).
- **`codebase`**: a change in the code: `step`, `headline`, `paths` (1 to 4),
  optional `points`.
- **`step`** is the build step: the approved plan's start waves, 1 first.
  Steps never go back and never skip. Changes built side by side share one.
- At least one user and one codebase change. Frame text is at most 70
  characters. No other frame type, image or page, and no line or frame that
  names a graph or a bench: `check` refuses them.

Write every `say` as the voice reads it, literally: respell paths, numbers and
abbreviations as a person says them. About 90 seconds by default (`--target`);
over it by more than 10% is refused.

`build` renders frames with playwright-core's Chromium (`OPENWIZ_CHROMIUM`, or
`chromium` on PATH), voices each line, and stitches a 30 fps H.264/AAC MP4 with
ffmpeg, verifying its tracks, length and sound. The default voice is the
machine's (espeak-ng, espeak or say); a better one is
`--tts-command "<cmd>"`, which reads the line on stdin or as `{text}` and writes
`{out}.wav` (or `.mp3`). Frames, voice files and `sheet.png` land in `build/`
beside the storyboard. The output path must be new. Keep authorization tokens
and private-media URLs out of a public issue.
