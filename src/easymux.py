#!/usr/bin/env python3
"""Persistent terminal workspaces powered by an isolated tmux server."""

import argparse
import contextlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

WORDS = ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine')
VERSION = '1.0.0'


class EasyMuxError(Exception):
    pass


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', action='version', version='easymux ' + VERSION)
    workspace = p.add_mutually_exclusive_group()
    for word in WORDS:
        workspace.add_argument('--' + word, dest='workspace', action='store_const', const=word)
    layout = p.add_mutually_exclusive_group()
    layout.add_argument('--duo', dest='panes', action='store_const', const=2,
                        help='two terminals side by side')
    layout.add_argument('--trio', dest='panes', action='store_const', const=3,
                        help='three terminals side by side')
    agent = p.add_mutually_exclusive_group()
    for name in ('claude', 'codex'):
        agent.add_argument('--' + name, dest='agent', action='store_const', const=name,
                           help='start ' + name + ' in every pane of a new workspace')
    actions = p.add_mutually_exclusive_group()
    actions.add_argument('--list', action='store_true', help='list EasyMux sessions')
    actions.add_argument('--kill', nargs='?', const='', metavar='WORKSPACE',
                         help='kill a workspace by number, word, or session name; defaults to current/selected/one')
    actions.add_argument('--killall', action='store_true', help='kill all EasyMux sessions')
    p.add_argument('--detach', action='store_true', help='create/resume without attaching')
    return p


def session_name(value):
    value = value.removeprefix('easymux-')
    if value in [str(n) for n in range(1, 10)]:
        value = WORDS[int(value) - 1]
    if value not in WORDS:
        raise EasyMuxError('Workspace must be 1–9, one–nine, or easymux-one–easymux-nine.')
    return 'easymux-' + value


class Tmux:
    def __init__(self):
        self.executable = shutil.which('tmux')
        if not self.executable:
            raise EasyMuxError('tmux is missing. Run the installer with --install-deps.')
        self.socket = os.environ.get('EASYMUX_SOCKET', 'easymux')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', self.socket):
            raise EasyMuxError('EASYMUX_SOCKET may contain only letters, numbers, underscores, and hyphens.')
        self.command = [self.executable, '-L', self.socket, '-f', '/dev/null']
        version = self.run('-V').stdout.strip()
        match = re.search(r'tmux (\d+)\.(\d+)', version)
        if not match or tuple(map(int, match.groups())) < (3, 1):
            raise EasyMuxError('EasyMux requires tmux 3.1 or later. Upgrade tmux, then retry.')

    def run(self, *args, check=True):
        result = subprocess.run(self.command + list(args), text=True, capture_output=True)
        if check and result.returncode:
            raise EasyMuxError(result.stderr.strip() or 'tmux command failed.')
        return result

    def sessions(self):
        result = self.run('list-sessions', '-F', '#{session_name}', check=False)
        if result.returncode:
            message = result.stderr.lower()
            if (message.startswith('no server running') or
                    ('error connecting to ' in message and 'no such file or directory' in message)):
                return []
            raise EasyMuxError(result.stderr.strip() or 'Unable to list tmux sessions.')
        return result.stdout.splitlines()

    def inside(self):
        if not os.environ.get('TMUX'):
            return False
        result = self.run('display-message', '-p', '#{socket_path}', check=False)
        return result.returncode == 0 and result.stdout.strip() == os.environ['TMUX'].rsplit(',', 2)[0]

    def current(self):
        if not self.inside() or not os.environ.get('TMUX_PANE'):
            return None
        return self.run('display-message', '-p', '-t', os.environ['TMUX_PANE'],
                        '#{session_name}').stdout.strip()

    @contextlib.contextmanager
    def locked(self):
        import fcntl
        state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'easymux'
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (state / (self.socket + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def create(self, name, count, agent):
        executable = shutil.which(agent) if agent else None
        if agent and not executable:
            raise EasyMuxError(f'{agent} is not on PATH. Install and sign in to {agent} first'
                               ' (inside WSL on Windows).')
        shell = os.environ.get('SHELL', '/bin/sh')
        if not os.path.isfile(shell) or not os.access(shell, os.X_OK):
            shell = '/bin/sh'
        # Invoke via sh so startup commands also work with fish as the user's shell.
        command = 'exec ' + shlex.quote(shell) + ' -l'
        if executable:
            command = shlex.quote(executable) + '; ' + command
        launch = 'exec /bin/sh -c ' + shlex.quote(command)
        size = shutil.get_terminal_size((180, 54))
        cwd = os.getcwd()
        env = ['-e', 'PATH=' + os.environ.get('PATH', os.defpath), '-e', 'SHELL=' + shell]
        # Generous initial dimensions allow creation even from a small terminal.
        first = self.run('new-session', '-d', '-P', '-F', '#{pane_id}', '-s', name,
                         '-n', 'workspace', '-x', str(max(size.columns, 90)),
                         '-y', str(max(size.lines - 1, 30)), '-c', cwd, *env,
                         'exec sleep 86400').stdout.strip()
        try:
            self.run('set-option', '-t', name, 'mouse', 'on')
            self.run('set-option', '-t', name, 'default-shell', shell)
            self.run('set-option', '-t', name, '@easymux_panes', str(count))
            self.run('set-option', '-t', name, '@easymux_agent', agent or 'shell')
            self.run('set-option', '-t', name, 'status-left', '[#S] ')
            self.run('set-option', '-t', name, 'status-left-length', '30')
            self.run('set-option', '-t', name, 'status-right', 'Mouse: select/resize | C-b d: detach')
            self.run('set-option', '-t', name, 'status-right-length', '50')
            self.run('set-window-option', '-t', name, 'pane-active-border-style', 'fg=cyan')
            self.run('set-window-option', '-t', name, 'automatic-rename', 'off')

            def split(pane, direction, percent):
                return self.run('split-window', '-d', '-P', '-F', '#{pane_id}',
                                '-t', pane, direction, '-p', str(percent), '-c', cwd,
                                *env, 'exec sleep 86400').stdout.strip()

            if count == 2:
                panes = [first, split(first, '-h', 50)]
            else:
                second = split(first, '-h', 66)
                columns = [first, second, split(second, '-h', 50)]
                panes = list(columns)
                if count == 9:
                    # Split each column into thirds: exactly 3x3 at every aspect ratio.
                    for column in columns:
                        middle = split(column, '-v', 66)
                        panes.extend([middle, split(middle, '-v', 50)])
            for pane in panes:
                self.run('respawn-pane', '-k', '-t', pane, '-c', cwd, *env, launch)
            self.run('select-pane', '-t', first)
        except BaseException:
            self.run('kill-session', '-t', '=' + name, check=False)
            raise

    def attach(self, name):
        if self.inside():
            self.run('switch-client', '-t', '=' + name)
        else:
            os.execv(self.executable, self.command + ['attach-session', '-t', '=' + name])


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    management = args.list or args.kill is not None or args.killall
    if management and (args.agent or args.panes or args.detach):
        p.error('session management cannot be combined with layout, agent, or --detach flags')
    if (args.list or args.killall) and args.workspace:
        p.error('--list and --killall apply to every workspace; omit the workspace flag')
    if args.kill and args.workspace:
        p.error('use either --kill WORKSPACE or --WORKSPACE --kill')
    try:
        if os.name == 'nt':
            raise EasyMuxError('Run install.ps1 to install the Windows launcher using WSL.')
        tmux = Tmux()
        name = session_name(args.workspace or 'one')
        with tmux.locked():
            sessions = tmux.sessions()
            if args.list:
                if not sessions:
                    print('No EasyMux sessions.')
                else:
                    print('SESSION\tWINDOWS\tCLIENTS\tLAYOUT\tCOMMAND')
                    print(tmux.run('list-sessions', '-F',
                                   '#{session_name}\t#{session_windows}\t#{session_attached}'
                                   '\t#{@easymux_panes} panes\t#{@easymux_agent}').stdout, end='')
                return 0
            if args.killall:
                if sessions:
                    tmux.run('kill-server')
                print('Killed all EasyMux sessions.' if sessions else 'No EasyMux sessions.')
                return 0
            if args.kill is not None:
                name = (session_name(args.kill) if args.kill else
                        name if args.workspace else tmux.current() or name)
                if name not in sessions:
                    raise EasyMuxError(f'No session named {name}. Use --list to see sessions.')
                tmux.run('kill-session', '-t', '=' + name)
                print('Killed ' + name + '.')
                return 0
            if not args.detach:
                if not sys.stdin.isatty() or not sys.stdout.isatty():
                    raise EasyMuxError('Open easymux in an interactive terminal, or use --detach.')
                if os.environ.get('TMUX') and not tmux.inside():
                    raise EasyMuxError('Detach from your other tmux server first (Ctrl-b d), then run easymux.')
            if name in sessions:
                for requested, key in [(args.panes, '@easymux_panes'), (args.agent, '@easymux_agent')]:
                    if requested is not None:
                        existing = tmux.run('show-options', '-v', '-t', name, key).stdout.strip()
                        if str(requested) != existing:
                            raise EasyMuxError(f'{name} already exists with different settings. '
                                               'Choose another workspace, or kill it before recreating it.')
            else:
                tmux.create(name, args.panes or 9, args.agent)
        if args.detach:
            print(name)
        else:
            tmux.attach(name)
        return 0
    except (EasyMuxError, OSError) as error:
        print('easymux: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
