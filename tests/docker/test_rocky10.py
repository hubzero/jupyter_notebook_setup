"""
Rocky Linux 10 compatibility tests for jpkg, start_jupyter and start_jupyterlab.

Meant to run inside the container built by run-docker-test.sh, as an ordinary user, with the
repository at $JUPYTER_TEST_REPO.  Nothing is stubbed: the scripts are loaded as they ship and run
against the real Rocky 10 tools (ps, find, cp, octave from EPEL, ...).

JUPYTER_TEST_NETWORK=0 skips the tests that reach the Anaconda archive.
JUPYTER_TEST_ANACONDA=1 also downloads the Anaconda installer and runs it.
"""

import argparse
import contextlib
import importlib.machinery
import io
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest
import warnings
from unittest import mock

REPO = os.environ.get('JUPYTER_TEST_REPO',
                      os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
NETWORK = os.environ.get('JUPYTER_TEST_NETWORK', '1') == '1'
ANACONDA = os.environ.get('JUPYTER_TEST_ANACONDA', '0') == '1'


def load_script(name, filename):
    """Import one of the extension-less scripts as a module."""
    path = os.path.join(REPO, filename)
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_launcher(filename):
    # start_jupyter works out the app name at import time; give it a tool directory to parse.
    with mock.patch.dict(os.environ, {'TOOLDIR': '/apps/mytool/r12'}):
        module = load_script(filename, filename)
    # Both launchers install signal handlers on import; put the defaults back so the test run
    # can still be interrupted and doesn't log every child exit.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGCHLD):
        signal.signal(sig, signal.SIG_DFL)
    return module


def prereq_packages():
    with open(os.path.join(REPO, 'jpkg')) as f:
        for line in f:
            if line.startswith('#   dnf install -y '):
                return line.split()[4:]
    raise AssertionError('no prerequisite line in jpkg')


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, **kw)


class TestPlatform(unittest.TestCase):
    """The host provides what jpkg's prerequisite comment promises."""

    def test_rocky_10(self):
        with open('/etc/os-release') as f:
            info = dict(line.rstrip('\n').split('=', 1) for line in f if '=' in line)
        self.assertEqual(info['ID'].strip('"'), 'rocky')
        self.assertEqual(info['VERSION_ID'].strip('"').split('.')[0], '10')

    def test_prereq_packages_installed(self):
        for pkg in prereq_packages():
            with self.subTest(pkg=pkg):
                self.assertEqual(run(['rpm', '-q', pkg]).returncode, 0, pkg)

    def test_commands_used_by_the_scripts(self):
        # which: find_octave, configs/r_7.  setfacl: nbextensions/inboxes.py.
        # python: the '#!/usr/bin/env python' shebangs.  bzip2: the Anaconda installer.
        for cmd in ('which', 'bzip2', 'tar', 'xz', 'curl', 'git', 'patch',
                    'find', 'ps', 'setfacl', 'python', 'octave'):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(shutil.which(cmd), cmd)

    def test_unversioned_python_is_python3(self):
        out = run(['python', '-c', 'import sys; print(sys.version_info[0])'])
        self.assertEqual(out.stdout.strip(), '3')

    def test_lang_set_by_jpkg_is_available(self):
        # jpkg sets LANG=en_US.UTF-8 for the whole install.
        locales = run(['locale', '-a']).stdout.lower().split()
        self.assertIn('en_us.utf8', locales)


class TestSyntax(unittest.TestCase):
    """Python 3.12 turns invalid escape sequences into SyntaxWarnings; there should be none."""

    def sources(self):
        files = ['jpkg', 'start_jupyter', 'start_jupyterlab']
        for root, dirs, names in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in ('.git', 'tests')]
            files += [os.path.relpath(os.path.join(root, n), REPO) for n in names if n.endswith('.py')]
        return sorted(files)

    def test_compiles_without_warnings(self):
        for rel in self.sources():
            with self.subTest(file=rel):
                with open(os.path.join(REPO, rel)) as f:
                    src = f.read()
                with warnings.catch_warnings():
                    warnings.simplefilter('error', SyntaxWarning)
                    compile(src, rel, 'exec')


class TestJpkgCommandLine(unittest.TestCase):

    def test_help_through_shebang(self):
        out = run([os.path.join(REPO, 'jpkg'), '--help'], env=dict(os.environ, COLUMNS='200'))
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn('/apps/share64/rocky10/environ.d', out.stdout)

    def test_jupyter_tool_through_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            nb = os.path.join(tmp, 'nb.ipynb')
            with open(nb, 'w') as f:
                json.dump({'metadata': {}, 'cells': [], 'nbformat': 4, 'nbformat_minor': 2}, f)
            out = run([os.path.join(REPO, 'jupyter_tool.py'), '-t', nb])
            self.assertEqual(out.returncode, 0, out.stdout)
            self.assertIn('notebook type is TOOL', out.stdout)
            with open(nb) as f:
                self.assertIs(json.load(f)['metadata']['tool'], True)


class TestJpkg(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.jpkg = load_script('jpkg', 'jpkg')
        cls.jpkg.dirname = REPO

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())

    def test_find_octave_desktop_uses_real_octave(self):
        kernel = self.jpkg.find_octave('/opt/anaconda-7', True, '/nonexistent', prompt=False)
        self.assertIsNotNone(kernel, 'octave was installed but not detected')
        kernel = json.loads(kernel)
        version = run(['rpm', '-q', '--qf', '%{VERSION}', 'octave']).stdout.strip()
        self.assertEqual(kernel['display_name'], 'Octave %s' % version)
        self.assertEqual(kernel['env']['OCTAVE_EXECUTABLE'], shutil.which('octave'))
        self.assertEqual(kernel['argv'][0], '/opt/anaconda-7/bin/python')

    def test_find_octave_hub_module(self):
        env_dir = os.path.join(self.tmp, 'environ.d')
        os.mkdir(env_dir)
        for ver in ('8.4', '9.2'):
            with open(os.path.join(env_dir, 'octave-' + ver), 'w') as f:
                f.write('desc "Octave"\n\nprepend PATH /apps/share64/rocky10/octave-%s/bin\n' % ver)
        kernel = json.loads(self.jpkg.find_octave('/opt/anaconda-7', False, env_dir, prompt=False))
        self.assertEqual(kernel['display_name'], 'Octave 9.2')
        self.assertEqual(kernel['env']['OCTAVE_EXECUTABLE'], '/apps/share64/rocky10/octave-9.2/bin/octave')
        self.assertEqual(kernel['env']['OCTAVE_HOME'], '/apps/share64/rocky10/octave-9.2')

    def test_find_octave_hub_without_module(self):
        self.assertIsNone(self.jpkg.find_octave('/opt/anaconda-7', False, self.tmp, prompt=False))

    def test_install_octave_writes_kernel(self):
        os.makedirs(os.path.join(self.tmp, 'share', 'jupyter', 'kernels'))
        self.jpkg.install_octave(self.tmp, '/nonexistent', True)
        with open(os.path.join(self.tmp, 'share', 'jupyter', 'kernels', 'octave', 'kernel.json')) as f:
            self.assertEqual(json.load(f)['name'], 'octave')

    def test_check_perm_fixes_modes(self):
        private = os.path.join(self.tmp, 'private')
        shared = os.path.join(self.tmp, 'shared')
        for path, mode in ((private, 0o600), (shared, 0o666)):
            with open(path, 'w'):
                pass
            os.chmod(path, mode)
        self.jpkg.check_perm(self.tmp)
        self.assertEqual(stat.S_IMODE(os.stat(private).st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(shared).st_mode), 0o664)

    def test_write_env(self):
        env_dir = os.path.join(self.tmp, 'environ.d')
        instpath = os.path.join(self.tmp, 'anaconda-7')
        self.jpkg.write_env('7', env_dir, instpath)
        with open(os.path.join(env_dir, 'anaconda-7')) as f:
            text = f.read()
        self.assertIn('version=7\n', text)
        self.assertIn('prepend PATH %s/bin\n' % instpath, text)

    def write_scripts(self, themes):
        bindir = os.path.join(self.tmp, 'bin')
        os.mkdir(bindir)
        os.symlink('/usr/bin/python3', os.path.join(bindir, 'python'))
        self.jpkg.write_start_scripts(REPO, bindir, themes)
        return bindir

    def assert_script_runs(self, bindir, name, *args):
        path = os.path.join(bindir, name)
        with open(path) as f:
            self.assertEqual(f.readline(), '#!%s/python\n' % bindir)
        self.assertTrue(os.access(path, os.X_OK))
        out = run([path] + list(args), env=dict(os.environ, TOOLDIR='/apps/mytool/r12'))
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertNotIn('Warning', out.stdout)
        self.assertIn('usage:', out.stdout)

    def test_start_scripts(self):
        bindir = self.write_scripts(None)
        self.assert_script_runs(bindir, 'start_jupyter', '-h')
        self.assert_script_runs(bindir, 'start_jupyterlab', '-h')

    def test_start_scripts_with_themes(self):
        # The themes package isn't installed, so --themes falls back to the normal main().
        bindir = self.write_scripts('nanohubthemes')
        with open(os.path.join(bindir, 'start_jupyter')) as f:
            self.assertIn('from nanohubthemes import main as themesMain', f.read())
        self.assert_script_runs(bindir, 'start_jupyter', '--themes', '-h')


def install_args(**kw):
    """The options make_new reads, as argparse would give them for a plain `install T`."""
    args = dict(ver='T', with_nanohub=False, desktop=True, with_py2=False, with_ml=False,
                with_vnc=False, with_dash=False, envdir='/nonexistent', no_notebooks=True,
                themes=None, with_r=False)
    args.update(kw)
    return argparse.Namespace(**args)


class FakeInstall(object):
    """A configs directory and installer that let make_new run for real in a few seconds."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.tmp)
        # make_new puts the new tree's bin first on PATH; keep that out of the other tests.
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.jpkg = load_script('jpkg', 'jpkg')
        self.jpkg.dirname = self.tmp
        os.mkdir('configs')

    def config(self, name, body, installer='fake-installer.sh'):
        with open(os.path.join('configs', name), 'w') as f:
            if name.startswith('base_conda_'):
                f.write('#ver=%s\n' % installer)
            f.write(body)

    def installer(self, body='mkdir -p "$3/bin"\n'):
        with open('fake-installer.sh', 'w') as f:
            f.write(body)

    def make_new(self, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                self.jpkg.make_new(install_args(**kw))
                code = None
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def order(self):
        if not os.path.exists('order'):
            return []
        with open('order') as f:
            return f.read().split()


class TestInstallErrors(FakeInstall, unittest.TestCase):

    def jpkg_install(self, *options):
        # The real jpkg and the real configs, in an empty directory.
        return run([os.path.join(REPO, 'jpkg'), '--envdir', os.path.join(self.tmp, 'environ.d')]
                   + list(options), cwd=self.tmp)

    def test_missing_nanohub_configs(self):
        os.rmdir('configs')
        out = self.jpkg_install('--with-nanohub', 'install', '7')
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn('configs/nanohub_conda_7', out.stdout)
        self.assertIn('configs/nanohub_pip_7', out.stdout)
        self.assertEqual(os.listdir(self.tmp), [], 'nothing should be downloaded or installed')

    def test_missing_configs_listed_together(self):
        out = self.jpkg_install('--with-ml', '--with-py2', 'install', '7')
        self.assertEqual(out.returncode, 1, out.stdout)
        error = [line for line in out.stdout.splitlines() if line.startswith('Error:')]
        self.assertEqual(len(error), 1, out.stdout)
        self.assertIn('configs/ml_7', error[0])
        self.assertIn('configs/python2_7', error[0])

    def test_unknown_version(self):
        out = self.jpkg_install('install', '99')
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn('configs/base_conda_99', out.stdout)
        self.assertNotIn('Traceback', out.stdout)

    def test_failing_config_line_stops_install(self):
        self.installer()
        self.config('base_conda_T', 'echo base_conda >> order\ntrue\nfalse\ntouch after-false\n')
        self.config('base_pip_T', 'echo base_pip >> order\n')
        code, out = self.make_new()
        self.assertEqual(code, 1, out)
        self.assertFalse(os.path.exists('after-false'))
        self.assertEqual(self.order(), ['base_conda'])
        self.assertIn('configs/base_conda_T', out)

    def test_failing_installer_stops_install(self):
        self.installer('exit 3\n')
        self.config('base_conda_T', 'echo base_conda >> order\n')
        self.config('base_pip_T', 'echo base_pip >> order\n')
        code, out = self.make_new()
        self.assertEqual(code, 1, out)
        self.assertIn('status 3', out)
        self.assertEqual(self.order(), [])

    def test_clean_install_completes(self):
        self.installer()
        for name in ('base_conda_T', 'base_pip_T', 'r_T'):
            self.config(name, 'echo %s >> order\n' % name[:-2])
        code, out = self.make_new(with_r=True)
        self.assertIsNone(code, out)
        self.assertEqual(self.order(), ['base_conda', 'base_pip', 'r'])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'anaconda-T', 'bin')))


class LauncherTests(object):
    """Shared by both launchers: recovering the session from `ps auxwwe`."""

    launcher = None

    def test_get_session_from_ps(self):
        # A process of ours that still carries the hub session in its environment.
        sleeper = subprocess.Popen(['env', '-i', 'SESSIONDIR=/tmp/sessions/4321', 'DISPLAY=:7',
                                    'sleep', '60'])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        time.sleep(0.5)
        env = {k: v for k, v in os.environ.items() if k not in ('SESSION', 'SESSIONDIR', 'DISPLAY')}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.launcher.get_session(), ('4321', '/tmp/sessions/4321'))
            self.assertEqual(os.environ['DISPLAY'], ':7')

    def test_get_proxy_addr(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'resources'), 'w') as f:
                f.write('hub_url https://nanohub.org\nfilexfer_port 8123\nfilexfer_cookie abcdef\n')
            with mock.patch.dict(os.environ, {'SESSION': '4321', 'SESSIONDIR': tmp}):
                self.assertEqual(self.launcher.get_proxy_addr(),
                                 ('/weber/4321/abcdef/123/',
                                  'https://proxy.nanohub.org/weber/4321/abcdef/123/'))


class TestStartJupyter(LauncherTests, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.launcher = load_launcher('start_jupyter')

    def test_parse_app_name(self):
        self.assertEqual(self.launcher.app_name, 'mytool')

    def published_tool(self, tmp, copy):
        tool = os.path.join(tmp, 'apps', 'mytool', 'r12')
        os.makedirs(os.path.join(tool, 'bin'))
        for name in ('bin/tool.ipynb', 'bin/helper.py'):
            with open(os.path.join(tool, name), 'w') as f:
                f.write(name)
        results = os.path.join(tmp, 'results')
        os.mkdir(results)
        with mock.patch.dict(os.environ, {'RESULTSDIR': results}):
            nb_dir, nb_name = self.launcher.find_notebook('tool.ipynb', tool, copy, [])
        self.assertEqual((nb_dir, nb_name), (os.path.join(results, 'mytool', 'bin'), 'tool.ipynb'))
        return nb_dir

    def test_find_notebook_links_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            nb_dir = self.published_tool(tmp, False)
            self.assertTrue(os.path.islink(os.path.join(nb_dir, 'tool.ipynb')))
            self.assertTrue(os.path.islink(os.path.join(nb_dir, 'helper.py')))

    def test_find_notebook_copies_notebooks(self):
        # -c: the find ... -exec cp ... \; pass replaces the notebook links with copies.
        with tempfile.TemporaryDirectory() as tmp:
            nb_dir = self.published_tool(tmp, True)
            notebook = os.path.join(nb_dir, 'tool.ipynb')
            self.assertFalse(os.path.islink(notebook))
            with open(notebook) as f:
                self.assertEqual(f.read(), 'bin/tool.ipynb')
            self.assertTrue(os.path.islink(os.path.join(nb_dir, 'helper.py')))


class TestStartJupyterlab(LauncherTests, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.launcher = load_launcher('start_jupyterlab')


@unittest.skipUnless(NETWORK, 'JUPYTER_TEST_NETWORK=0')
class TestAnacondaDownload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        jpkg = load_script('jpkg', 'jpkg')
        jpkg.dirname = REPO
        cls.script = jpkg.get_scriptname('7')
        cls.url = 'https://repo.continuum.io/archive/%s' % cls.script

    def test_installer_url_follows_redirect(self):
        # repo.continuum.io answers with a redirect; jpkg's curl -L has to follow it to get the
        # installer rather than saving the redirect page.  Only the first KB is fetched.
        out = subprocess.run(['curl', '-L', '-s', '-f', '-r', '0-1023', self.url],
                             stdout=subprocess.PIPE)
        self.assertEqual(out.returncode, 0)
        self.assertTrue(out.stdout.startswith(b'#!/bin/sh'), out.stdout[:80])

    @unittest.skipUnless(ANACONDA, 'pass --anaconda to run the Anaconda installer')
    def test_installer_runs(self):
        # The download and install commands make_new uses, then a smoke test of the result.
        with tempfile.TemporaryDirectory(dir=os.path.expanduser('~')) as tmp:
            self.assertEqual(subprocess.call('curl -L -O %s' % self.url, shell=True, cwd=tmp), 0)
            instpath = os.path.join(tmp, 'anaconda-7')
            self.assertEqual(subprocess.call('bash %s -b -p %s' % (self.script, instpath),
                                             shell=True, cwd=tmp), 0)
            out = run([os.path.join(instpath, 'bin', 'python'), '-c',
                       'import ssl, sqlite3, numpy; print("ok")'])
            self.assertEqual(out.stdout.strip().splitlines()[-1], 'ok', out.stdout)
            out = run([os.path.join(instpath, 'bin', 'conda'), '--version'])
            self.assertEqual(out.returncode, 0, out.stdout)


@unittest.skipUnless(NETWORK, 'JUPYTER_TEST_NETWORK=0')
class TestInstallDownload(FakeInstall, unittest.TestCase):

    def test_download_404_fails(self):
        # Without curl -f the 404 page would be saved as the installer and handed to bash.
        self.config('base_conda_T', 'echo base_conda >> order\n', installer='NoSuch-Installer.sh')
        self.config('base_pip_T', '')
        code, out = self.make_new()
        self.assertEqual(code, 1, out)
        self.assertFalse(os.path.exists('NoSuch-Installer.sh'))
        self.assertEqual(self.order(), [])


if __name__ == '__main__':
    unittest.main()
