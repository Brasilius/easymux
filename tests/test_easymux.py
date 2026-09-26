import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'src/easymux.py'
spec = importlib.util.spec_from_file_location('easymux', CLI)
easymux = importlib.util.module_from_spec(spec)
spec.loader.exec_module(easymux)


class Arguments(unittest.TestCase):
    def test_workspace_aliases(self):
        for number, word in enumerate(easymux.WORDS, 1):
            for alias in (str(number), word, 'easymux-' + word):
                self.assertEqual(easymux.session_name(alias), 'easymux-' + word)
        for invalid in ('0', '10', 'easymux-', '*', 'one;kill-server', 'other'):
            with self.assertRaises(easymux.EasyMuxError):
                easymux.session_name(invalid)

    def test_conflicting_options(self):
        for args in (['--one', '--nine'], ['--duo', '--trio'], ['--claude', '--codex'],
                     ['--list', '--killall'], ['--kill', '--codex'], ['--list', '--one'],
                     ['--kill', 'two', '--one'], ['--killall', '--detach'], ['--unknown']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    easymux.main(args)
                self.assertEqual(error.exception.code, 2)

    def test_missing_tmux_is_actionable(self):
        with patch.object(shutil, 'which', return_value=None):
            with self.assertRaisesRegex(easymux.EasyMuxError, 'install-deps'):
                easymux.Tmux()

    def test_failed_creation_removes_partial_workspace(self):
        version = subprocess.CompletedProcess([], 0, 'tmux 3.1c\n', '')
        with patch.object(shutil, 'which', return_value='/usr/bin/tmux'), \
                patch.object(subprocess, 'run', return_value=version):
            tmux = easymux.Tmux()
        result = subprocess.CompletedProcess([], 0, '%0\n', '')
        with patch.object(tmux, 'run', side_effect=[result, easymux.EasyMuxError('failure'), result]) as run:
            with self.assertRaisesRegex(easymux.EasyMuxError, 'failure'):
                tmux.create('easymux-one', 9, None)
            self.assertEqual(run.call_args.args, ('kill-session', '-t', '=easymux-one'))


@unittest.skipUnless(shutil.which('tmux'), 'tmux is required for integration tests')
class Workspaces(unittest.TestCase):
    def setUp(self):
        # Keep Unix socket paths short enough on macOS as well as Linux.
        self.temp = tempfile.TemporaryDirectory(prefix='em-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.env = dict(os.environ, HOME=str(self.directory), SHELL='/bin/sh',
                        XDG_STATE_HOME=str(self.directory / 'state'), TMUX_TMPDIR=self.temp.name,
                        EASYMUX_SOCKET='easymux-test', TERM='xterm-256color')
        self.env.pop('TMUX', None)
        self.env.pop('TMUX_PANE', None)
        self.addCleanup(lambda: self.tmux('kill-server', check=False))

    def cli(self, *args, check=True):
        result = subprocess.run([sys.executable, str(CLI), *args], env=self.env,
                                cwd=self.directory, capture_output=True, text=True, timeout=20)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def tmux(self, *args, check=True, socket='easymux-test'):
        result = subprocess.run(['tmux', '-L', socket, '-f', '/dev/null', *args],
                                env=self.env, capture_output=True, text=True, timeout=10)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def panes(self, workspace='one'):
        return self.tmux('list-panes', '-t', 'easymux-' + workspace, '-F',
                         '#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height}').stdout.splitlines()

    def test_grid_mouse_directory_and_resume(self):
        self.cli('--detach')
        original = self.panes()
        self.assertEqual(len(original), 9)
        positions = [tuple(map(int, line.split()[1:3])) for line in original]
        self.assertEqual(len(set(x for x, y in positions)), 3)
        self.assertEqual(len(set(y for x, y in positions)), 3)
        self.assertEqual(len(set(positions)), 9)
        self.assertEqual(self.tmux('show-options', '-v', '-t', 'easymux-one', 'mouse').stdout.strip(), 'on')
        paths = self.tmux('list-panes', '-t', 'easymux-one', '-F', '#{pane_current_path}').stdout.splitlines()
        self.assertEqual(paths, [str(self.directory)] * 9)
        first = original[0].split()[0]
        self.tmux('resize-pane', '-t', first, '-R', '2')
        resized = self.panes()
        self.cli('--one', '--detach')
        self.assertEqual(self.panes(), resized)
        self.assertIn('easymux-one', self.cli('--list').stdout)

    def test_duo_trio_and_all_workspace_names(self):
        for number, word in enumerate(easymux.WORDS):
            layout, count = ('--duo', 2) if number % 2 == 0 else ('--trio', 3)
            self.cli('--' + word, layout, '--detach')
            panes = self.panes(word)
            self.assertEqual(len(panes), count)
            self.assertEqual(len({p.split()[2] for p in panes}), 1)
        self.assertEqual(len(self.cli('--list').stdout.splitlines()), 10)

    def test_exact_kill_and_isolated_killall(self):
        self.tmux('new-session', '-d', '-s', 'unrelated', socket='other-test')
        self.addCleanup(lambda: self.tmux('kill-server', socket='other-test', check=False))
        self.cli('--one', '--duo', '--detach')
        self.cli('--two', '--trio', '--detach')
        self.cli('--kill', '1')
        listing = self.cli('--list').stdout
        self.assertNotIn('easymux-one', listing)
        self.assertIn('easymux-two', listing)
        self.cli('--killall')
        self.assertIn('No EasyMux sessions', self.cli('--list').stdout)
        self.tmux('has-session', '-t', '=unrelated', socket='other-test')
        self.cli('--killall')
        self.assertNotEqual(self.cli('--kill', 'two', check=False).returncode, 0)

    def test_selected_and_current_workspace_kill(self):
        self.cli('--two', '--duo', '--detach')
        self.cli('--three', '--duo', '--detach')
        self.cli('--two', '--kill')
        pane = self.panes('three')[0].split()[0]
        socket = self.tmux('display-message', '-p', '#{socket_path}').stdout.strip()
        self.env.update(TMUX=socket + ',123,0', TMUX_PANE=pane)
        self.cli('--kill')
        self.assertIn('No EasyMux sessions', self.cli('--list').stdout)

    def test_incompatible_resume_preserves_processes(self):
        self.cli('--duo', '--detach')
        original = self.panes()
        result = self.cli('--trio', '--detach', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)
        self.assertEqual(self.panes(), original)

    def test_noninteractive_attach_does_not_create_workspace(self):
        result = self.cli(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('interactive terminal', result.stderr)
        self.assertIn('No EasyMux sessions', self.cli('--list').stdout)

    def test_interactive_mouse_focus_resize_and_detach(self):
        import fcntl
        import pty
        import struct
        import termios

        pid, terminal = pty.fork()
        if pid == 0:
            os.chdir(self.directory)
            os.execve(sys.executable, [sys.executable, str(CLI)], self.env)
        try:
            fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 120, 0, 0))

            def wait_for(predicate):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if select.select([terminal], [], [], 0.05)[0]:
                        os.read(terminal, 65536)
                    if predicate():
                        return
                self.fail('Interactive terminal did not reach expected state.')

            wait_for(lambda: '1' in self.tmux('list-sessions', '-F', '#{session_attached}',
                                              check=False).stdout)
            panes = self.panes()
            right_top = next(line.split() for line in panes
                             if int(line.split()[1]) > 50 and line.split()[2] == '0')
            pane, left, top, width, height = right_top
            x, y = int(left) + 3, int(top) + 3
            os.write(terminal, f'\x1b[<0;{x};{y}M\x1b[<0;{x};{y}m'.encode())
            wait_for(lambda: self.tmux('display-message', '-p', '-t', 'easymux-one',
                                       '#{pane_id}').stdout.strip() == pane)
            # Drag the border to the left of the focused pane three cells right.
            x = int(left)
            os.write(terminal, f'\x1b[<0;{x};{y}M\x1b[<32;{x + 3};{y}M'
                              f'\x1b[<0;{x + 3};{y}m'.encode())
            wait_for(lambda: self.panes() != panes)
            os.write(terminal, b'\x02d')
            wait_for(lambda: self.tmux('list-sessions', '-F', '#{session_attached}').stdout.strip() == '0')
            self.assertEqual(len(self.panes()), 9)
        finally:
            if os.waitpid(pid, os.WNOHANG)[0] == 0:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            os.close(terminal)

    def test_parallel_creation_reuses_complete_workspace(self):
        command = [sys.executable, str(CLI), '--detach']
        processes = [subprocess.Popen(command, env=self.env, cwd=self.directory,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(2)]
        results = [process.communicate(timeout=20) for process in processes]
        for process, (stdout, stderr) in zip(processes, results):
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), 'easymux-one')
        self.assertEqual(len(self.panes()), 9)

    def test_agents_run_in_every_pane_and_exit_to_shell(self):
        bin_dir = self.directory / "tools with ' spaces"
        bin_dir.mkdir()
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        for name, workspace in [('claude', 'one'), ('codex', 'two')]:
            marker = self.directory / (name + '.log')
            self.env['EASYMUX_TEST_LOG'] = str(marker)
            fake = bin_dir / name
            fake.write_text('#!/bin/sh\nprintf "started\\n" >> "$EASYMUX_TEST_LOG"\n')
            fake.chmod(0o755)
            # tmux retains its server environment, so explicitly set the log for the second agent.
            if workspace == 'two':
                self.tmux('set-environment', '-g', 'EASYMUX_TEST_LOG', str(marker))
            self.cli('--' + workspace, '--' + name, '--detach')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if marker.exists() and len(marker.read_text().splitlines()) == 9:
                    break
                time.sleep(0.05)
            self.assertTrue(marker.exists())
            self.assertEqual(len(marker.read_text().splitlines()), 9)
            self.assertEqual(len(self.panes(workspace)), 9)
            dead = self.tmux('list-panes', '-t', 'easymux-' + workspace, '-F', '#{pane_dead}').stdout.splitlines()
            self.assertEqual(dead, ['0'] * 9)


class Installer(unittest.TestCase):
    def test_install_is_repeatable_with_spaces_in_home(self):
        with tempfile.TemporaryDirectory(prefix='easymux home ') as temp:
            home = Path(temp)
            bin_dir = home / 'test-bin'
            bin_dir.mkdir()
            tmux = bin_dir / 'tmux'
            tmux.write_text('#!/bin/sh\nexit 0\n')
            tmux.chmod(0o755)
            env = dict(os.environ, HOME=temp, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
                       SHELL='/bin/bash', ZDOTDIR=str(home / 'zsh'))
            profile = home / '.profile'
            profile.write_text('# existing user config\nexport KEEP_ME=yes\n')
            for _ in range(2):
                result = subprocess.run(['bash', str(ROOT / 'install.sh')], env=env,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
            installed = home / '.local/bin/easymux'
            self.assertTrue(os.access(installed, os.X_OK))
            result = subprocess.run([str(installed), '--version'], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(easymux.VERSION, result.stdout)
            self.assertEqual(profile.read_text().count('# easymux:'), 1)
            self.assertIn('KEEP_ME=yes', profile.read_text())
            self.assertTrue((home / 'zsh/.zshrc').exists())


if __name__ == '__main__':
    unittest.main()
