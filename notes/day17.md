# Greenlight - Day 17 notes

## The demo's colors were wrong, and I'd checked the wrong thing

Told that "green isn't really visible, it looks like colorblind mode", I
opened the committed GIF and counted colors. It was true: the palette was
48 colors chosen by the quantizer from the frames, and most of those went
to near-black background shades. Green (63,185,80) had become a gray-green
(122,142,137); red had become (199,137,124). The preview images I'd
reviewed were the frames *before* they were squeezed into a GIF palette, so
they looked fine. I'd inspected the input to the file, not the file.

Fixed by building the palette on purpose (a ramp of anti-aliasing shades
for each text color on the window background) and making the build script
reopen the finished GIF and fail if green, yellow or red aren't actually
in it. It also exposed that the new file is smaller, not bigger.

## The PyPI page had a broken image all along

Same README, different renderer. PyPI renders the long description without
the repository around it, so `examples/demo.gif` and five other relative
links resolve to nothing. The published page has shown a broken demo image
since the first version that had one. Checked it against the live JSON
metadata rather than assuming; made the links absolute.

## Payload capture: the decision

The biggest functional gap against the Inspector and mcpsnoop: greenlight
could say a call failed and how long it took, but never what arguments the
client sent. The reason it couldn't was a deliberate privacy stance, logs
hold metadata only, so reversing it silently would have been wrong.

Picked: opt-in, off by default, redacted before writing. Not "on with
redaction", because redaction is best effort and a default has to be safe
without it. The things that make that defensible:

- Redaction happens before the write, so a secret it catches never exists
  in the file. The test greps the raw file for the secret, since a parsed
  field check could pass while the file still holds it.
- It also covers things greenlight already recorded (error text, tool error
  text, raw non-JSON stdout lines), which had the same exposure and were
  never redacted.
- A failed result carries the arguments that caused it. Without that you'd
  have to match ids by hand, which is exactly the chore the feature is for.
- `serve` returns payloads only when asked: the person opting into capture
  isn't necessarily opting every agent session into reading it.

Limits, stated in the README rather than discovered later: a secret in free
text matching no known shape gets through; keys named like secrets are
redacted even when harmless (`tokenizer: "gpt2"` is hidden); numbers under
those keys are kept (`max_tokens`).

## A bug found by looking at real output

`tail --payloads` is supposed to print each payload on one line, cut at the
terminal edge. Reading the real output, the long lines wrapped. Rich
ignores `no_wrap`/`overflow` set on the `Text` object and honors them only
as `print()` arguments. Changed it, and added an assertion that fails if
payloads wrap again (checked by putting the bug back and watching the test
fail).
