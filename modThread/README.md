# RSCBot: transactions

The `modThread` cog is primarily responsible for assigning and managing ModMail channels to the appropriate "category" for processing by a specific team.

## Installation

The `modThread` cog does not have any other cog requirements.

```
<p>cog install RSCBot modThread
<p>load modThread
```

## Usage

Before using, you most likely need to set the RulesCategory, NumbersCategory, and ModsCategory. These categories are where ModMail channels will be moved when the `<p> assign` command is received.

- `<p>assign <numbers|rules|mods>`
  - Assigns the modmail message to the appropriate committee and pings them.
  
- `<p>setPrimaryCategory <primary_category>`
  - Sets the category that all modmails start in. This is needed to make sure we're not randomly moving other channels around as if they were a modmail.
- `<p>getPrimaryCategory`
  - Returns the primary category if one has been set.
- `<p>unsetPrimaryCategory`
  - Unsets primary category

- `<p>setNumbersCategory <numbers_category>`
  - Sets the category to move ModMail messages into for Numbers Committee
- `<p>getNumbersCategory`
  - Returns the numbers category if one has been set.
- `<p>unsetNumbersCategory`
  - Unsets transaction channel
- `<p>setNumbersRole <Role>`
  - Sets the role to ping when a ticket is assigned to that committee.

- `<p>setRulesCategory <rules_category>`
  - Sets the category to move ModMail messages into for Rules Committee
- `<p>getRulesCategory`
  - Returns the rules category if one has been set.
- `<p>unsetRulesCategory`
  - Unsets transaction channel
- `<p>setRulesRole <Role>`
  - Sets the role to ping when a ticket is assigned to that committee.

- `<p>setModsCategory <mods_category>`
  - Sets the category to move ModMail messages into for Mods Committee
- `<p>getModsCategory`
  - Returns the mods category if one has been set.
- `<p>unsetModsCategory`
  - Unsets transaction channel
- `<p>setModsRole <Role>`
  - Sets the role to ping when a ticket is assigned to that committee.