# You are running under cryo on a Fly.io Sprite

This machine can restart at any moment (cold wake, host move, checkpoint
restore). cryo freezes this session to disk and brings it back afterwards, so
just keep working. If a tool call or a request to the model fails right after a
restart, retry it once.

## Reporting your work

When you finish a task, email the result to the owner through the Sprites
Resend connector. The API key is not on this machine; the Sprites gateway adds
it on the way out. Use:

    cryo report --subject "<short subject>" --file <path to your report>

`cryo` is at /home/sprite/cryo/cryo. If it isn't on PATH, call it by that path.

To see which connectors this Sprite can use:

    curl -s https://api.sprites.dev/v1/gateway/list

## Experiments

Other agents on this machine are live, and people may be watching them. If you
want to try cryo on a throwaway process, give it its own state folder so it
can't see or touch the real agents:

    export CRYO_HOME=<a folder in your scratchpad>

Never run `cryo stop`, `thaw`, `freeze` or `teleport` on an agent you didn't
start yourself, and stop your own test agents when you're done.
