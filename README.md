# EasyMux

Type `easymux` to open a persistent **3×3 grid of terminals** in your current terminal window and working directory. Click a pane to select it, drag a border to resize, and use the mouse wheel to scroll. Detach and return later without restarting your processes.

EasyMux uses [tmux](https://github.com/tmux/tmux/wiki) on Linux and macOS, and tmux inside [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) on Windows. Windows panes run Linux shells and tools. Requires **tmux 3.1+ and Python 3.9+**; no Python packages are needed.

## Install

Download or clone this repository, then run the installer from its directory. The installers can be rerun to update EasyMux.

### Linux and macOS

```sh
bash install.sh --install-deps
```

This installs missing dependencies using apt, dnf, pacman, zypper, apk, or Homebrew. macOS requires [Homebrew](https://brew.sh) to be installed first. Package installation may request your sudo password. If the dependencies are already installed, `bash install.sh` is sufficient.

The command is installed to `~/.local/bin/easymux`, with idempotent PATH additions to Bash and Zsh startup files (and Fish configuration if Fish is your current shell). Open a new terminal, or enable it in your current Bash/Zsh shell:

```sh
export PATH="$HOME/.local/bin:$PATH"
easymux
```

Do not run the whole installer with sudo: it installs for the user running it. On distributions with older packages, upgrade to the required Python and tmux versions first.

### Windows

Install WSL first if necessary: run `wsl --install` from an administrator PowerShell, restart if prompted, then launch the Linux distribution and complete its user setup. From a regular PowerShell in this repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -InstallDeps
```

The installer uses the default WSL distribution, or select one explicitly:

```powershell
.\install.ps1 -Distro Ubuntu -InstallDeps
```

It installs the Linux command inside that distribution and a Windows launcher at `%LOCALAPPDATA%\EasyMux\bin\easymux.cmd`, adding that directory to your user PATH. Open a new terminal and type `easymux`. Running `install.ps1` directly also updates the current PowerShell's PATH. Use a terminal with mouse reporting, such as Windows Terminal. The launcher remembers the selected distribution; it does not follow later changes to your default distribution. Windows working directories are passed through WSL's normal directory translation.

## Commands

| Command | Behavior |
| --- | --- |
| `easymux` | Create or resume workspace one; new workspaces default to a 3×3 grid. |
| `easymux --one` … `easymux --nine` | Create or resume one of nine independent workspaces. |
| `easymux --duo` | Create workspace one with two terminals side by side. |
| `easymux --trio` | Create workspace one with three terminals side by side. |
| `easymux --claude` | Create workspace one with nine Claude sessions. |
| `easymux --codex` | Create workspace one with nine Codex sessions. |
| `easymux --list` | List EasyMux sessions, windows, attached clients, and original layout/command. |
| `easymux --kill two` | Terminate workspace two and its processes. Also accepts `2` or `easymux-two`. |
| `easymux --two --kill` | Terminate workspace two or any other workspace. |
| `easymux --kill` | Terminate the current EasyMux workspace, or workspace one when outside EasyMux. |
| `easymux --killall` | Terminate all EasyMux workspaces and their processes. |
| `easymux --detach` | Create/resume without attaching, useful from scripts. |
| `easymux --help` | Show all options. |

Workspace, layout, and agent flags can be combined:

```sh
easymux --two --claude       # Nine Claude sessions in workspace two
easymux --three --codex      # Nine Codex sessions in workspace three
easymux --four --duo        # Two shell panes in workspace four
easymux --five --trio --codex
```

Install the `claude` or `codex` command and complete its sign-in before launching an agent workspace. On Windows, install these **inside the selected WSL distribution**. EasyMux uses the executable on your PATH and preserves the tools' normal permission prompts. Each pane starts an independent session; when the agent exits, the pane returns to your login shell.

An existing workspace resumes with its processes and resized layout intact. Explicitly requesting a different layout or agent for that workspace gives an error. Use another workspace or terminate the old one with `--kill` before recreating it. Simply running `easymux --two` resumes workspace two regardless of its original layout or agent.

## Mouse and keyboard

- Click inside a pane to focus it; drag pane borders to resize.
- Scroll with the mouse wheel; press `q` to leave tmux's scroll/copy mode.
- Press **Ctrl-b**, then **d** to detach while leaving sessions running.
- Press **Ctrl-b**, then an arrow key to move between panes.
- Press **Ctrl-b**, then **z** to zoom/unzoom the current pane.
- Press **Ctrl-b**, then **s** to choose a session.

Text selection uses tmux copy mode. System clipboard integration depends on your terminal; holding Shift (or your terminal's mouse override modifier) lets the terminal handle selection directly. Enlarge the terminal or zoom a pane if nine panes feel cramped.

Workspaces survive detaching and closing the terminal, but not a machine reboot, WSL shutdown, or exiting every pane. EasyMux uses a dedicated tmux server named `easymux`, with no user tmux configuration, so regular tmux sessions are separate. Running EasyMux within an EasyMux pane switches sessions; detach from other tmux servers before attaching to EasyMux.

For manual inspection: `tmux -L easymux list-sessions`. `EASYMUX_SOCKET` can select another dedicated server (letters, numbers, underscores, and hyphens only). `--killall` kills the entire selected server, so reserve it for EasyMux. Creation and management are serialized using a lock under `${XDG_STATE_HOME:-~/.local/state}/easymux`.

## Development

```sh
python3 -m unittest discover -s tests -v
bash -n install.sh
```

Integration tests require tmux and use temporary homes and isolated sockets. They check exact grid geometry, working directories, persistence, concurrent creation, side-by-side layouts, agent startup, and session termination isolation. A pseudo-terminal test checks attachment, mouse selection, border dragging, and detachment. Without tmux, integration tests are skipped. The CI configuration runs the full suite on Linux and macOS and checks PowerShell syntax on Windows. Terminal-specific mouse behavior and the complete WSL installer still require a real terminal/Windows smoke test.
