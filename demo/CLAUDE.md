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
