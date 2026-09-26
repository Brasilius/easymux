#!/usr/bin/env bash
# Linux, macOS, and WSL installer. Run from this checkout; no Python packages needed.
set -euo pipefail

install_deps=false
case "${1:-}" in
    --install-deps) install_deps=true ;;
    --help|-h) echo 'Usage: bash install.sh [--install-deps]'; exit 0 ;;
    '') ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then echo 'Too many arguments.' >&2; exit 2; fi

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
platform="$(uname -s)"
case "$platform" in
    Linux|Darwin) ;;
    MINGW*|MSYS*|CYGWIN*) echo 'Run .\install.ps1 from PowerShell to install with WSL.' >&2; exit 1 ;;
    *) echo "Unsupported operating system: $platform" >&2; exit 1 ;;
esac

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

if ! command -v tmux >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
    if ! "$install_deps"; then
        echo 'tmux and Python 3.9+ are required. Rerun: bash install.sh --install-deps' >&2
        exit 1
    fi
    if [ "$platform" = Darwin ]; then
        if ! command -v brew >/dev/null 2>&1; then
            echo 'Install Homebrew from https://brew.sh, then rerun this installer.' >&2
            exit 1
        fi
        brew install tmux python
    elif command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update
        as_root apt-get install -y tmux python3
    elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y tmux python3
    elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -S --needed --noconfirm tmux python
    elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install tmux python3
    elif command -v apk >/dev/null 2>&1; then
        as_root apk add tmux python3
    else
        echo 'Install tmux and Python 3.9+ using your package manager, then rerun.' >&2
        exit 1
    fi
fi

python3 - "$source_dir" "$platform" <<'PY'
import os
from pathlib import Path
import shlex
import shutil
import sys

if sys.version_info < (3, 9):
    sys.exit('EasyMux requires Python 3.9 or later. Upgrade Python, then rerun.')

source = Path(sys.argv[1]) / 'src/easymux.py'
home = Path.home()
bin_dir = home / '.local/bin'
bin_dir.mkdir(parents=True, exist_ok=True)
destination = bin_dir / 'easymux'
shutil.copyfile(source, destination)
destination.chmod(0o755)
wsl_launcher = bin_dir / 'easymux-wsl'
shutil.copyfile(source.parent / 'easymux-wsl', wsl_launcher)
wsl_launcher.chmod(0o755)

# Idempotent PATH additions cover login and interactive shells on both platforms.
marker = '# easymux: user executables'
posix_block = ('\n' + marker + '\n'
               'case ":$PATH:" in\n'
               '  *":$HOME/.local/bin:"*) ;;\n'
               '  *) export PATH="$HOME/.local/bin:$PATH" ;;\n'
               'esac\n')
zsh_dir = Path(os.environ.get('ZDOTDIR') or str(home))
profiles = [home / '.profile', home / '.bashrc', zsh_dir / '.zshrc', zsh_dir / '.zprofile']
# Bash ignores .profile when either of these exists. macOS starts login shells.
if (home / '.bash_profile').exists() or sys.argv[2] == 'Darwin':
    profiles.append(home / '.bash_profile')
elif (home / '.bash_login').exists():
    profiles.append(home / '.bash_login')
for profile in dict.fromkeys(profiles):
    profile.parent.mkdir(parents=True, exist_ok=True)
    old = profile.read_text() if profile.exists() else ''
    if marker not in old:
        # Preserve an existing login chain when creating .bash_profile on macOS.
        extra = ''
        if profile.name == '.bash_profile' and not profile.exists():
            prior = home / ('.bash_login' if (home / '.bash_login').exists() else '.profile')
            extra = '\n[ ! -f ' + shlex.quote(str(prior)) + ' ] || . ' + shlex.quote(str(prior)) + '\n'
        with profile.open('a') as output:
            output.write(extra + posix_block)
if Path(os.environ.get('SHELL', '')).name == 'fish':
    fish = Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'fish/conf.d/easymux.fish'
    fish.parent.mkdir(parents=True, exist_ok=True)
    fish.write_text('if not contains -- "$HOME/.local/bin" $PATH\n'
                    '    set -gx PATH "$HOME/.local/bin" $PATH\nend\n')
print('Installed ' + str(destination))
print('Open a new terminal, then run: easymux')
print('For this shell now: export PATH="$HOME/.local/bin:$PATH"')
PY
