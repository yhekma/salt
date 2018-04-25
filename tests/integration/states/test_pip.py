# -*- coding: utf-8 -*-
'''
    :codeauthor: :email:`Pedro Algarvio (pedro@algarvio.me)`


    tests.integration.states.pip
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
'''

# Import python libs
from __future__ import absolute_import
import errno
import os
import glob
import shutil
import sys

try:
    import pwd
    HAS_PWD = True
except ImportError:
    HAS_PWD = False

# Import Salt Testing libs
from tests.support.mixins import SaltReturnAssertsMixin
from tests.support.unit import skipIf
from tests.support.runtests import RUNTIME_VARS
from tests.support.helpers import (
    destructiveTest,
    requires_system_grains,
    with_system_user,
    skip_if_not_root
)
# Import salt libs
from tests.support.case import ModuleCase
import salt.utils
import salt.utils.win_functions
from salt.modules.virtualenv_mod import KNOWN_BINARY_NAMES
from salt.exceptions import CommandExecutionError

# Import 3rd-party libs
import salt.ext.six as six


class VirtualEnv(object):
    def __init__(self, test, venv_dir):
        self.venv_dir = venv_dir
        self.test = test

    def __enter__(self):
        ret = self.test.run_function('virtualenv.create', [self.venv_dir])
        self.test.assertEqual(ret['retcode'], 0)

    def __exit__(self, exc_type, exc_value, traceback):
        if os.path.isdir(self.venv_dir):
            shutil.rmtree(self.venv_dir, ignore_errors=True)


@skipIf(salt.utils.which_bin(KNOWN_BINARY_NAMES) is None, 'virtualenv not installed')
class PipStateTest(ModuleCase, SaltReturnAssertsMixin):

    @skip_if_not_root
    def test_pip_installed_removed(self):
        '''
        Tests installed and removed states
        '''
        name = 'pudb'
        if name in self.run_function('pip.list'):
            self.skipTest('{0} is already installed, uninstall to run this test'.format(name))
        ret = self.run_state('pip.installed', name=name)
        self.assertSaltTrueReturn(ret)
        ret = self.run_state('pip.removed', name=name)
        self.assertSaltTrueReturn(ret)

    def test_pip_installed_removed_venv(self):
        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, 'pip_installed_removed'
        )
        with VirtualEnv(self, venv_dir):
            name = 'pudb'
            ret = self.run_state('pip.installed', name=name, bin_env=venv_dir)
            self.assertSaltTrueReturn(ret)
            ret = self.run_state('pip.removed', name=name, bin_env=venv_dir)
            self.assertSaltTrueReturn(ret)

    def test_pip_installed_errors(self):
        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, 'pip-installed-errors'
        )
        orig_shell = os.environ.get('SHELL')
        try:
            # Since we don't have the virtualenv created, pip.installed will
            # throw an error.
            # Example error strings:
            #  * "Error installing 'pep8': /tmp/pip-installed-errors: not found"
            #  * "Error installing 'pep8': /bin/sh: 1: /tmp/pip-installed-errors: not found"
            #  * "Error installing 'pep8': /bin/bash: /tmp/pip-installed-errors: No such file or directory"
            os.environ['SHELL'] = '/bin/sh'
            ret = self.run_function('state.sls', mods='pip-installed-errors')
            self.assertSaltFalseReturn(ret)
            self.assertSaltCommentRegexpMatches(
                ret,
                'Error installing \'pep8\':'
            )

            # We now create the missing virtualenv
            ret = self.run_function('virtualenv.create', [venv_dir])
            self.assertEqual(ret['retcode'], 0)

            # The state should not have any issues running now
            ret = self.run_function('state.sls', mods='pip-installed-errors')
            self.assertSaltTrueReturn(ret)
        finally:
            if orig_shell is None:
                # Didn't exist before, don't leave it there. This should never
                # happen, but if it does, we don't want this test to affect
                # others elsewhere in the suite.
                os.environ.pop('SHELL')
            else:
                os.environ['SHELL'] = orig_shell
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

    @skipIf(six.PY3, 'Issue is specific to carbon module, which is PY2-only')
    @skipIf(salt.utils.is_windows(), "Carbon does not install in Windows")
    @requires_system_grains
    def test_pip_installed_weird_install(self, grains=None):
        # First, check to see if this is running on CentOS 5 or MacOS.
        # If so, skip this test.
        if grains['os'] in ('CentOS',) and grains['osrelease_info'][0] in (5,):
            self.skipTest('This test does not run reliably on CentOS 5')
        if grains['os'] in ('MacOS',):
            self.skipTest('This test does not run reliably on MacOS')

        ographite = '/opt/graphite'
        if os.path.isdir(ographite):
            self.skipTest(
                'You already have \'{0}\'. This test would overwrite this '
                'directory'.format(ographite)
            )
        try:
            os.makedirs(ographite)
        except OSError as err:
            if err.errno == errno.EACCES:
                # Permission denied
                self.skipTest(
                    'You don\'t have the required permissions to run this test'
                )
        finally:
            if os.path.isdir(ographite):
                shutil.rmtree(ographite, ignore_errors=True)

        venv_dir = os.path.join(RUNTIME_VARS.TMP, 'pip-installed-weird-install')
        try:
            # We may be able to remove this, I had to add it because the custom
            # modules from the test suite weren't available in the jinja
            # context when running the call to state.sls that comes after.
            self.run_function('saltutil.sync_modules')
            # Since we don't have the virtualenv created, pip.installed will
            # throw an error.
            ret = self.run_function(
                'state.sls', mods='pip-installed-weird-install'
            )
            self.assertSaltTrueReturn(ret)

            # We cannot use assertInSaltComment here because we need to skip
            # some of the state return parts
            for key in six.iterkeys(ret):
                self.assertTrue(ret[key]['result'])
                if ret[key]['name'] != 'carbon < 1.1':
                    continue
                self.assertEqual(
                    ret[key]['comment'],
                    'There was no error installing package \'carbon < 1.1\' '
                    'although it does not show when calling \'pip.freeze\'.'
                )
                break
            else:
                raise Exception('Expected state did not run')
        finally:
            if os.path.isdir(ographite):
                shutil.rmtree(ographite, ignore_errors=True)

    def test_issue_2028_pip_installed_state(self):
        ret = self.run_function('state.sls', mods='issue-2028-pip-installed')

        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, 'issue-2028-pip-installed'
        )

        pep8_bin = os.path.join(venv_dir, 'bin', 'pep8')
        if salt.utils.is_windows():
            pep8_bin = os.path.join(venv_dir, 'Scripts', 'pep8.exe')

        try:
            self.assertSaltTrueReturn(ret)
            self.assertTrue(
                os.path.isfile(pep8_bin)
            )
        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

    def test_issue_2087_missing_pip(self):
        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, 'issue-2087-missing-pip'
        )

        try:
            # Let's create the testing virtualenv
            ret = self.run_function('virtualenv.create', [venv_dir])
            self.assertEqual(ret['retcode'], 0)

            # Let's remove the pip binary
            pip_bin = os.path.join(venv_dir, 'bin', 'pip')
            py_dir = 'python{0}.{1}'.format(*sys.version_info[:2])
            site_dir = os.path.join(venv_dir, 'lib', py_dir, 'site-packages')
            if salt.utils.is_windows():
                pip_bin = os.path.join(venv_dir, 'Scripts', 'pip.exe')
                site_dir = os.path.join(venv_dir, 'lib', 'site-packages')
            if not os.path.isfile(pip_bin):
                self.skipTest(
                    'Failed to find the pip binary to the test virtualenv'
                )
            os.remove(pip_bin)

            # Also remove the pip dir from site-packages
            # This is needed now that we're using python -m pip instead of the
            # pip binary directly. python -m pip will still work even if the
            # pip binary is missing
            shutil.rmtree(os.path.join(site_dir, 'pip'))

            # Let's run the state which should fail because pip is missing
            ret = self.run_function('state.sls', mods='issue-2087-missing-pip')
            self.assertSaltFalseReturn(ret)
            self.assertInSaltComment(
                'Error installing \'pep8\': Could not find a `pip` binary',
                ret
            )
        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

    def test_issue_5940_multiple_pip_mirrors(self):
        '''
        Test multiple pip mirrors.  This test only works with pip < 7.0.0
        '''
        ret = self.run_function(
            'state.sls', mods='issue-5940-multiple-pip-mirrors'
        )

        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, '5940-multiple-pip-mirrors'
        )

        try:
            self.assertSaltTrueReturn(ret)
            self.assertTrue(
                os.path.isfile(os.path.join(venv_dir, 'bin', 'pep8'))
            )
        except (AssertionError, CommandExecutionError):
            pip_version = self.run_function('pip.version', [venv_dir])
            if salt.utils.compare_versions(ver1=pip_version, oper='>=', ver2='7.0.0'):
                self.skipTest('the --mirrors arg has been deprecated and removed in pip==7.0.0')
        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

    @destructiveTest
    @skip_if_not_root
    @skipIf(salt.utils.is_windows(), "password required on Windows")
    @with_system_user('issue-6912', on_existing='delete', delete=True)
    def test_issue_6912_wrong_owner(self, username):
        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, '6912-wrong-owner'
        )
        # ----- Using runas ------------------------------------------------->
        venv_create = self.run_function(
            'virtualenv.create', [venv_dir], user=username
        )
        if venv_create['retcode'] > 0:
            self.skipTest(
                'Failed to create testcase virtual environment: {0}'.format(
                    venv_create
                )
            )

        # Using the package name.
        try:
            ret = self.run_state(
                'pip.installed', name='pep8', user=username, bin_env=venv_dir
            )
            self.assertSaltTrueReturn(ret)
            if HAS_PWD:
                uid = pwd.getpwnam(username).pw_uid
            else:
                if salt.utils.is_windows():
                    uid = salt.utils.win_functions.get_sid_from_name(
                        salt.utils.win_functions.get_current_user()
                    )

            for globmatch in (os.path.join(venv_dir, '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '*', '**', 'pep8*')):
                for path in glob.glob(globmatch):
                    self.assertequal(uid, os.stat(path).st_uid)

        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

        # using a requirements file
        venv_create = self.run_function(
            'virtualenv.create', [venv_dir], user=username
        )
        if venv_create['retcode'] > 0:
            self.skiptest(
                'failed to create testcase virtual environment: {0}'.format(
                    ret
                )
            )
        req_filename = os.path.join(
            RUNTIME_VARS.TMP_STATE_TREE, 'issue-6912-requirements.txt'
        )
        with salt.utils.fopen(req_filename, 'wb') as reqf:
            reqf.write(six.b('pep8'))

        try:
            ret = self.run_state(
                'pip.installed', name='', user=username, bin_env=venv_dir,
                requirements='salt://issue-6912-requirements.txt'
            )
            self.assertSaltTrueReturn(ret)
            if HAS_PWD:
                uid = pwd.getpwnam(username).pw_uid
            else:
                if salt.utils.is_windows():
                    uid = salt.utils.win_functions.get_sid_from_name(
                        salt.utils.win_functions.get_current_user()
                    )
            for globmatch in (os.path.join(venv_dir, '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '*', '**', 'pep8*')):
                for path in glob.glob(globmatch):
                    self.assertEqual(uid, os.stat(path).st_uid)

        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)
            os.unlink(req_filename)
        # <---- Using runas --------------------------------------------------

        # ----- Using user -------------------------------------------------->
        venv_create = self.run_function(
            'virtualenv.create', [venv_dir], user=username
        )
        if venv_create['retcode'] > 0:
            self.skipTest(
                'Failed to create testcase virtual environment: {0}'.format(
                    ret
                )
            )

        # Using the package name
        try:
            ret = self.run_state(
                'pip.installed', name='pep8', user=username, bin_env=venv_dir
            )
            self.assertSaltTrueReturn(ret)
            if HAS_PWD:
                uid = pwd.getpwnam(username).pw_uid
            else:
                if salt.utils.is_windows():
                    uid = salt.utils.win_functions.get_sid_from_name(
                        salt.utils.win_functions.get_current_user()
                    )
            for globmatch in (os.path.join(venv_dir, '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '*', '**', 'pep8*')):
                for path in glob.glob(globmatch):
                    self.assertEqual(uid, os.stat(path).st_uid)

        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

        # Using a requirements file
        venv_create = self.run_function(
            'virtualenv.create', [venv_dir], user=username
        )
        if venv_create['retcode'] > 0:
            self.skipTest(
                'Failed to create testcase virtual environment: {0}'.format(
                    ret
                )
            )
        req_filename = os.path.join(
            RUNTIME_VARS.TMP_STATE_TREE, 'issue-6912-requirements.txt'
        )
        with salt.utils.fopen(req_filename, 'wb') as reqf:
            reqf.write(six.b('pep8'))

        try:
            ret = self.run_state(
                'pip.installed', name='', user=username, bin_env=venv_dir,
                requirements='salt://issue-6912-requirements.txt'
            )
            self.assertSaltTrueReturn(ret)
            if HAS_PWD:
                uid = pwd.getpwnam(username).pw_uid
            else:
                if salt.utils.is_windows():
                    uid = salt.utils.win_functions.get_sid_from_name(
                        salt.utils.win_functions.get_current_user()
                    )
            for globmatch in (os.path.join(venv_dir, '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '**', 'pep8*'),
                              os.path.join(venv_dir, '*', '*', '**', 'pep8*')):
                for path in glob.glob(globmatch):
                    self.assertEqual(uid, os.stat(path).st_uid)

        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)
            os.unlink(req_filename)
        # <---- Using user ---------------------------------------------------

    def test_issue_6833_pip_upgrade_pip(self):
        # Create the testing virtualenv
        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, '6833-pip-upgrade-pip'
        )
        ret = self.run_function('virtualenv.create', [venv_dir])

        try:
            try:
                self.assertEqual(ret['retcode'], 0)
                self.assertIn(
                    'New python executable',
                    ret['stdout']
                )
            except AssertionError:
                import pprint
                pprint.pprint(ret)
                raise

            # Let's install a fixed version pip over whatever pip was
            # previously installed
            ret = self.run_function(
                'pip.install', ['pip==8.0'], upgrade=True,
                bin_env=venv_dir
            )
            try:
                self.assertEqual(ret['retcode'], 0)
                self.assertIn(
                    'Successfully installed pip',
                    ret['stdout']
                )
            except AssertionError:
                import pprint
                pprint.pprint(ret)
                raise

            # Let's make sure we have pip 8.0 installed
            self.assertEqual(
                self.run_function('pip.list', ['pip'], bin_env=venv_dir),
                {'pip': '8.0.0'}
            )

            # Now the actual pip upgrade pip test
            ret = self.run_state(
                'pip.installed', name='pip==8.0.1', upgrade=True,
                bin_env=venv_dir
            )
            try:
                self.assertSaltTrueReturn(ret)
                self.assertSaltStateChangesEqual(
                    ret, {'pip==8.0.1': 'Installed'})
            except AssertionError:
                import pprint
                pprint.pprint(ret)
                raise
        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

    def test_pip_installed_specific_env(self):
        # Create the testing virtualenv
        venv_dir = os.path.join(
            RUNTIME_VARS.TMP, 'pip-installed-specific-env'
        )

        # Let's write a requirements file
        requirements_file = os.path.join(
            RUNTIME_VARS.TMP_PRODENV_STATE_TREE, 'prod-env-requirements.txt'
        )
        with salt.utils.fopen(requirements_file, 'wb') as reqf:
            reqf.write(six.b('pep8\n'))

        try:
            self.run_function('virtualenv.create', [venv_dir])

            # The requirements file should not be found the base environment
            ret = self.run_state(
                'pip.installed', name='', bin_env=venv_dir,
                requirements='salt://prod-env-requirements.txt'
            )
            self.assertSaltFalseReturn(ret)
            self.assertInSaltComment(
                "'salt://prod-env-requirements.txt' not found", ret
            )

            # The requirements file must be found in the prod environment
            ret = self.run_state(
                'pip.installed', name='', bin_env=venv_dir, saltenv='prod',
                requirements='salt://prod-env-requirements.txt'
            )
            self.assertSaltTrueReturn(ret)
            self.assertInSaltComment(
                'Successfully processed requirements file '
                'salt://prod-env-requirements.txt', ret
            )

            # We're using the base environment but we're passing the prod
            # environment as an url arg to salt://
            ret = self.run_state(
                'pip.installed', name='', bin_env=venv_dir,
                requirements='salt://prod-env-requirements.txt?saltenv=prod'
            )
            self.assertSaltTrueReturn(ret)
            self.assertInSaltComment(
                'Requirements were already installed.',
                ret
            )
        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)
            if os.path.isfile(requirements_file):
                os.unlink(requirements_file)

    def test_22359_pip_installed_unless_does_not_trigger_warnings(self):
        # This test case should be moved to a format_call unit test specific to
        # the state internal keywords
        venv_dir = os.path.join(RUNTIME_VARS.TMP, 'pip-installed-unless')
        venv_create = self.run_function('virtualenv.create', [venv_dir])
        if venv_create['retcode'] > 0:
            self.skipTest(
                'Failed to create testcase virtual environment: {0}'.format(
                    venv_create
                )
            )

        false_cmd = '/bin/false'
        if salt.utils.is_windows():
            false_cmd = 'exit 1 >nul'
        try:
            ret = self.run_state(
                'pip.installed', name='pep8', bin_env=venv_dir, unless=false_cmd
            )
            self.assertSaltTrueReturn(ret)
            self.assertNotIn('warnings', next(six.itervalues(ret)))
        finally:
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir, ignore_errors=True)

    @skipIf(sys.version_info[:2] >= (3, 6), 'Old version of virtualenv too old for python3.6')
    @skipIf(salt.utils.is_windows(), "Carbon does not install in Windows")
    def test_46127_pip_env_vars(self):
        '''
        Test that checks if env_vars passed to pip.installed are also passed
        to pip.freeze while checking for existing installations
        '''
        # This issue is most easily checked while installing carbon
        # Much of the code here comes from the test_weird_install function above
        ographite = '/opt/graphite'
        if os.path.isdir(ographite):
            self.skipTest(
                'You already have \'{0}\'. This test would overwrite this '
                'directory'.format(ographite)
            )
        try:
            os.makedirs(ographite)
        except OSError as err:
            if err.errno == errno.EACCES:
                # Permission denied
                self.skipTest(
                    'You don\'t have the required permissions to run this test'
                )
        finally:
            if os.path.isdir(ographite):
                shutil.rmtree(ographite, ignore_errors=True)

        venv_dir = os.path.join(RUNTIME_VARS.TMP, 'issue-46127-pip-env-vars')
        try:
            # We may be able to remove this, I had to add it because the custom
            # modules from the test suite weren't available in the jinja
            # context when running the call to state.sls that comes after.
            self.run_function('saltutil.sync_modules')
            # Since we don't have the virtualenv created, pip.installed will
            # throw an error.
            ret = self.run_function(
                'state.sls', mods='issue-46127-pip-env-vars'
            )
            self.assertSaltTrueReturn(ret)
            for key in six.iterkeys(ret):
                self.assertTrue(ret[key]['result'])
                if ret[key]['name'] != 'carbon < 1.3':
                    continue
                self.assertEqual(
                    ret[key]['comment'],
                    'All packages were successfully installed'
                )
                break
            else:
                raise Exception('Expected state did not run')
            # Run the state again. Now the already installed message should
            # appear
            ret = self.run_function(
                'state.sls', mods='issue-46127-pip-env-vars'
            )
            self.assertSaltTrueReturn(ret)
            # We cannot use assertInSaltComment here because we need to skip
            # some of the state return parts
            for key in six.iterkeys(ret):
                self.assertTrue(ret[key]['result'])
                # As we are re-running the formula, some states will not be run
                # and "name" may or may not be present, so we use .get() pattern
                if ret[key].get('name', '') != 'carbon < 1.3':
                    continue
                self.assertEqual(
                    ret[key]['comment'],
                    ('Python package carbon < 1.3 was already installed\n'
                     'All specified packages are already installed'))
                break
            else:
                raise Exception('Expected state did not run')
        finally:
            if os.path.isdir(ographite):
                shutil.rmtree(ographite, ignore_errors=True)
            if os.path.isdir(venv_dir):
                shutil.rmtree(venv_dir)
