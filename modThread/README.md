# RSCBot: transactions

The `modThread` cog is primarily responsible for assigning and managing ModMail channels to the appropriate "category" for processing by a specific team.

## Installation

The `modThread` cog does not have any other cog requirements.

```
<p>cog install RSCBot modThread
<p>load modThread
```

## Usage

Before using, you will need to configure modThread.

- `<p>modthread settings`
  - View the settings! 

- `<p>assign <group>`
  - Assigns the modmail message to the appropriate group and pings them.
- `<p>unassign`
  - Unassigns the modmail and returns it to the primary category.
  
- `<p>modthread groups add <group> <#category> <@role>`
  - Adds a group recipient list and defines their category as `<#category>` and pings `<@role>`.
- `<p>modthread groups add <group> <#category> <@role>`
  - Updates a group recipient list with `<#category>` and pings `<@role>`.
- `<p>modthread groups delete <group>`
  - Deletes a defined group.

- `<p>category <#category>`
  - Defines the primary entry-point category for all modmails.
- `<p>role <@role>`
  - Defines the primary role (admins usually) for inbound modmails.

- `<p>THERE_IS_A_SECRET_COMMAND`
  - Do **NOT** tell anyone about the secret command.
