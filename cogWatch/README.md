# RSCBot: cogWatch

The `cogWatch` cog records every time a cog is unloaded, and who or what did it. Use it to track down cogs that disappear from the bot unexpectedly.

It also counts how often each command is used in each guild, to show which cogs and commands are still in use.

Each unload is logged as a warning in Red's logs (`red.RSCBot.cogWatch`):

- Unloads from a command (`unload`, `reload`, `cog uninstall`) record the user, channel and the full command message.
- Unloads that don't come from a command record a call stack showing which code did it.

Unloads during bot shutdown are ignored. Only unloads that happen while `cogWatch` is loaded are recorded, including its own unload.

## Installation

The `cogWatch` cog is an independent redbot Cog with no dependencies.

```
<p>cog install bot-RSCBot cogWatch
<p>load cogWatch
```

## Usage

- `<p>cogwatch channel [channel]`
  - Sends an alert to a text channel whenever a cog is unloaded. Leave the channel blank to turn alerts off; unloads are still logged. Owner only.
- `<p>cogwatch usage`
  - Shows how many times each command has run since counting started, grouped by cog, with a per-guild breakdown. Also lists loaded cogs whose commands haven't been used. Owner only.
- `<p>cogwatch resetusage`
  - Clears all usage counts and starts counting again from now. Owner only.

## Usage counts

- Only commands that complete successfully are counted. Commands that fail a permission check or raise an error are not.
- Slash commands from `app_commands` and event listeners (for example, cogs that only react to joins or messages) are not counted.
- Counts are saved every 10 minutes and when the cog unloads, so a crash can lose up to 10 minutes of counts.
- Only totals are stored: no users, channels, messages or timestamps.
