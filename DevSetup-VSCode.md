# Developer Setup Instructions (Windows)

This set of instructions informs developers how to configure their dev environment for Red in VS Code. This process will enable devs to run redbot instances from their shell and should resolve any redbot import references.

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/):

     `$ powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

    - uv version can be viewed with:

         `$ uv --version`

1. Create the virtual environment and install dependencies (including Red-DiscordBot) from the project root:

    `$ uv sync`

    - This creates `.venv` using the Python version pinned in `.python-version` (uv downloads it if needed) and installs everything locked in `uv.lock`, including the `dev` dependency group.
    - Re-run `uv sync` whenever `pyproject.toml` or `uv.lock` changes. If running the code in debug mode is failing, this is the first thing to try.

1. At the bottom right of the IDE, a prompt may appear:

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;![](https://i.stack.imgur.com/HzSHk.png)

- _"We noticed a new virtual environment has been created. Do you want to select it for the workspace folder?"_
- Select **Yes**.

<br>

1. (Optional) Enter Virtual Environment with the command below. Alternatively, skip activation and prefix commands with `uv run` (e.g. `uv run redbot <instance>`).

     `$ & c:/Users/<path_to_project>/.venv/Scripts/Activate.ps1`

     or

     `$ ./.venv/Scripts/Activate.ps1` (using local path)
1. Use the hotkey (`Ctrl+Shift+P`) and click "Python: Select Interpreter"
    - Select the virtual environment you just created: `('.venv': venv) ./.venv/Scripts.python.exe`

# Installing Cogs for Development
For standard use, cogs are installed by adding the reference to a githubt repo, then installing and loading the cogs within that repo -- as described by this project's readme. However, if you wish to do development, particularly with debugging, then it there is a better alternative.

Instead of installing from a remote repo, load the code from the bot's local environment as described by the [Testing your cog](https://docs.discord.red/en/stable/guide_cog_creation.html#testing-your-cog) section of the official red docs.

Format:
```
<p>addpath C:\<path_to_local_code>\bot-RSCBot
<p>load <cog>
```
Example:

![](https://cdn.discordapp.com/attachments/825671516300902400/995068217728970782/unknown.png)

# Debugging
1. Open the debug window in VSC (`Ctrl+Shift+D`) and click the cog.
1. Update `.vscode/launch.json` to include the following as a configuration:
```json
{
    "name": "Python: RedBot",
    "type": "python",
    "request": "launch",
    "module": "redbot",
    "args": [
        "DEFAULT",
        "--dev",
        "--debug"
    ],
    "console": "externalTerminal"
}
```
1. replace `DEFAULT` with your instance name
1. Click the Run and Debug dropdown to select your newly created configuration, and the Green Play button to run it.

# More Shell Commands
- `uv run redbot --list` lists all redbot instances
- `uv run redbot <instance>` launches a redbot instance
- `uv run redbot-setup` creates a new redbot instance

# Normal Use

1. Run Bot Instance:

    - From Terminal:

        `$ uv run redbot <instance>` (+ optional flag: `--dev`)

    or

    - From Debug Console:

        - Click the Run and Debug dropdown to select your newly created configuration, and the Green Play button to run it.

# Helpful Data Information
It is likely that you may need to manually tweak some of the saved data in a cog's json file. When you set up the bot, you are prompted with a default location for where this bot will live and execute from. The default location will look something like this:

`C:\Users\<username>\AppData\Local\Red-DiscordBot\Red-DiscordBot\data\<your-bot-name>`

Unless you have installed a bot to a different location, all your bot instances will exist within the `/data/` folder. You can navigate into the bot instance folder to manipulate anything you need to get your hands on manually.

## Where should I look?
The `core` folder doesn't contain anything truly significant. It stores information such as the bot token, prefix(es), os, and installed cogs.

**This is likely the most helpful thing to know for manual debugging/bug fixing:**

\*\*The `cogs` folder has a greater quantity and quality of files within it. Most notably, each cog folder contains the `settings.json` file for the information saved for that cog respectively.

## Extra Info
It is worth identifying that there are two important cogs loaded by default: `CogManager` and `RepoManager`. In some edge cases, its helpful to dig into these repositories, particularly the `CogManager` as it stores the executable python files that are imported from a remote GitHub repository.
