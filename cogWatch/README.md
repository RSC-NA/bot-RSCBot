# RSCBot: cogWatch

The `cogWatch` cog records every time a cog is unloaded, and who or what did it. Use it to track down cogs that disappear from the bot unexpectedly.

Each unload is logged as a warning in Red's logs (`red.RSCBot.cogWatch`):

- Unloads from a command (`unload`, `reload`, `cog uninstall`) record the user, channel and the full command message.
- Unloads that don't come from a command record a call stack showing which code did it.

Unloads during bot shutdown are ignored. Only unloads that happen while `cogWatch` is loaded are recorded, including its own unload.

## Installation

The `cogWatch` cog is an independent redbot Cog with no dependencies.

```
<p>cog install RSCBot cogWatch
<p>load cogWatch
```

## Usage

- `<p>cogwatch channel [channel]`
  - Sends an alert to a text channel whenever a cog is unloaded. Leave the channel blank to turn alerts off; unloads are still logged. Owner only.
