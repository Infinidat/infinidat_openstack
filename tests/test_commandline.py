from infi.execute import execute_assert_success
from infi.unittest import TestCase, SkipTest
from infi.pyutils.contexts import contextmanager
from shutil import copy
from mock import patch
from os import path
import sys


EXPECTED_OUTPUT = """
+------------------------------------------------+-----------+---------+----------------------+---------------+------------------------------------------------+---------+---------------------------------------+
|                    address                     |  username | enabled |        status        | system serial |                  system name                   | pool id |               pool name               |
+------------------------------------------------+-----------+---------+----------------------+---------------+------------------------------------------------+---------+---------------------------------------+
| {system_name} | infinidat |   True  | connection successul |     {system_serial}     | {system_name} |   {pool_id}   | {pool_name} |
+------------------------------------------------+-----------+---------+----------------------+---------------+------------------------------------------------+---------+---------------------------------------+
"""

EXPECTED_FAILURE = """
+------------------------------------------------+-----------+---------+--------+---------------+-------------+---------+-----------+
|                    address                     |  username | enabled | status | system serial | system name | pool id | pool name |
+------------------------------------------------+-----------+---------+--------+---------------+-------------+---------+-----------+
| {system_name} | infinidat |   True  | error  |      n/a      |     n/a     |   {pool_id}   |    n/a    |
+------------------------------------------------+-----------+---------+--------+---------------+-------------+---------+-----------+
"""

class CommandlineTestsMixin(object):
    @classmethod
    def setUpClass(cls):
        cls.setup_infinibox()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_infinibox()

    def test_system_list__empty(self):
        pid = self.assert_command(["list"], stderr='')
        self.assertIn("---------", pid.get_stdout())

    def test_system_list(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)
        pid = self.assert_command(["list"], stderr='')
        self.assertIn(self.infinipy.get_name(), pid.get_stdout())
        self.assertIn(str(self.infinipy.get_serial()), pid.get_stdout())
        self.assertIn(pool.get_name(), pid.get_stdout())
        self.assertIn(str(pool.get_id()), pid.get_stdout())

    def test_set_and_remove(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)
        args = ["remove", self.infinipy.get_name(), str(pool.get_id())]
        pid = self.assert_command(args, stderr=stderr)

    def test_set_and_toggle_enable(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)
        args = ["enable", self.infinipy.get_name(), str(pool.get_id())]
        pid = self.assert_command(args, stderr=stderr)
        args = ["disable", self.infinipy.get_name(), str(pool.get_id())]
        pid = self.assert_command(args, stderr=stderr)

    def test_enable_non_existing_key(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["enable", self.infinipy.get_name(), str(pool.get_id())]
        stderr='failed to enable {}/{}, not found\n'.format(self.infinipy.get_name(), pool.get_id())
        pid = self.assert_command(args, stderr=stderr, return_code=1)

    def test_remove_non_existing_key(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["remove", self.infinipy.get_name(), str(pool.get_id())]
        stderr='failed to remove {}/{}, not found\n'.format(self.infinipy.get_name(), pool.get_id())
        pid = self.assert_command(args, stderr=stderr, return_code=1)

    def test_disable_non_existing_key(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["disable", self.infinipy.get_name(), str(pool.get_id())]
        stderr='failed to disable {}/{}, not found\n'.format(self.infinipy.get_name(), pool.get_id())
        pid = self.assert_command(args, stderr=stderr, return_code=1)

    def test_update_non_existing_key(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["update", self.infinipy.get_name(), str(pool.get_id())]
        stderr='failed to update {}/{}, not found\n'.format(self.infinipy.get_name(), pool.get_id())
        pid = self.assert_command(args, stderr=stderr, return_code=1)

    def test_remove__non_integer_pool_id(self):
        args = ["remove", self.infinipy.get_name(), "foo"]
        stderr = 'invalid pool id: foo\n'
        pid = self.assert_command(args, stderr=stderr, return_code=1)

    def test_set__invalid_credentials(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "1nfinidat", "123456"]
        stderr = 'InfiniBox API failed: You are not authorized for this operation\n'
        pid = self.assert_command(args, stderr=stderr, return_code=1)

    def test_credentials_file_missing(self):
        stderr = 'cinder environment file /path/does/not/exists does not exist\n'
        pid = self.assert_command(["list", "--rc-file=/path/does/not/exists"], stderr=stderr, return_code=1)

    def test_config_file_missing(self):
        stderr = 'cinder configuration file /path/does/not/exists does not exist\n'
        pid = self.assert_command(["list", "--config-file=/path/does/not/exists"], stderr=stderr, return_code=1)

    def test_update_after_pool_rename(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)
        pool.set_name("foo")
        args = ["update", self.infinipy.get_name(), str(pool.get_id())]
        pid = self.assert_command(args, stderr='done\n')

    def test_update_all(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)
        args = ["update", "all"]
        pid = self.assert_command(args, stderr='done\n')

    def assert_command(self, args, stderr=None, return_code=0):
        pid = self.execute(args)
        print pid.get_stdout()
        print pid.get_stderr()
        self.assertEquals(pid.get_returncode(), return_code)
        if stderr is not None:
            self.assertEquals(pid.get_stderr(), stderr)
        return pid


def deduce_config_files(cls, args):
    defaults = []
    if not any(arg.startswith("--config-file=") for arg in args):
        defaults.append("--config-file={0}".format(cls.CONFIG_FILE))
    if not any(arg.startswith("--rc-file=") for arg in args):
        defaults.append("--rc-file={0}".format(cls.RC_FILE))
    return defaults


class RealInfiniBoxMixin(object):
    @classmethod
    def setup_infinibox(cls):
        from infi.vendata.integration_tests import system_allocation
        cls.system = system_allocation.SystemFactory.allocate_infinidat_system()
        cls.infinipy = cls.system.get_infinipy()
        cls.infinipy.purge()

    @classmethod
    def teardown_infinibox(cls):
        try:
            cls.system.release()
        except:
            pass


class MockInfiniBoxMixin(object):
    @classmethod
    def setup_infinibox(cls):
        from infinisim import Simulator
        from infinipy import System
        cls.simulator = Simulator()
        cls.simulator.set_serial(12345)
        cls.infinipy = System(cls.simulator)

    @classmethod
    def teardown_infinibox(cls):
        pass


class RealTestCase(CommandlineTestsMixin, RealInfiniBoxMixin, TestCase):
    EXECUTABLE = "/usr/bin/openstack-infinibox-config"
    CONFIG_FILE = "/etc/cinder/cinder.conf"

    @classmethod
    def install_package(cls):
        from glob import glob
        packages = glob("dist/*rpm")
        if not packages:
            raise SkipTest("no packages found")
        execute_assert_success(["rpm", "-Uvh", packages[0]])

    @classmethod
    def remove_package(cls):
        execute_assert_success(["rpm", "-e", "infinidat_openstack"])

    @classmethod
    def setUpClass(cls):
        cls.install_package()
        if not path.exists(cls.EXECUTABLE):
            raise SkipTest("openstack plugin not installed")
        cls.setup_infinibox()

    @classmethod
    def tearDownClass(cls):
        super(RealTestCase, cls).tearDownClass()
        cls.remove_package()

    def execute(self, args):
        return execute_assert_success([self.EXECUTABLE] + args)

    def setUp(self):
        with open(self.CONFIG_FILE, 'r') as fd:
            before = fd.read()

        def restore():
            with open(self.CONFIG_FILE, 'w') as fd:
                fd.write(before)

        self.addCleanup(restor)


class MockTestCase(CommandlineTestsMixin, MockInfiniBoxMixin, TestCase):
    CONFIG_FILE = "tests/conf/commandline_tests.conf"
    RC_FILE = "tests/conf/commandline_tests.rc"

    @contextmanager
    def mock_print_context(self):
        from StringIO import StringIO

        def _print(text, stream=sys.stdout):
            if stream is sys.stdout:
                print >> stdout, text
            elif stream is sys.stderr:
                print >> stderr, text
            else:
                raise RuntimeError()

        stderr = StringIO()
        stdout = StringIO()

        with patch("infinidat_openstack.scripts._print", side_effect=_print):
            with patch("infinidat_openstack.scripts.TRACEBACK_FILE", new=stderr):
                yield stdout, stderr

    @contextmanager
    def mock_clients_context(self):
        from infinipy import System
        infinipy_side_effect = lambda address, username="infinidat", password="123456": System(self.simulator, username=username, password=password)
        with patch("infinipy.System", side_effect=infinipy_side_effect) as infinipy:
            with patch("cinderclient.v1.client.Client"):
                yield

    def setUp(self):
        with open(self.CONFIG_FILE, 'w') as fd:
            pass

    def execute(self, args):
        from infinidat_openstack import scripts
        from munch import Munch
        pid = Munch()
        with self.mock_clients_context(), self.mock_print_context() as (stdout, stderr):
            try:
                result = scripts.main(deduce_config_files(self, args) +  args)
            except SystemExit, error:
                result = error.code
        pid.get_returncode = lambda: int(0 if result is None else result)
        pid.get_stdout = lambda: stdout.getvalue()
        pid.get_stderr = lambda: stderr.getvalue()
        return pid

    def test_catching_general_exception(self):
        with patch("infinidat_openstack.scripts.handle_commands", side_effect=RuntimeError()):
            pid = self.assert_command(["list"], return_code=1)
            self.assertIn("RuntimeError", pid.get_stderr())

    def test_connection_to_cinderclient_fails(self):
        with patch("infinidat_openstack.scripts.get_cinder_client", side_effect=Exception()):
            pid = self.assert_command(["list"], return_code=1)
            self.assertIn("failed to connect to cinder service", pid.get_stderr())

    def test_system_list__exact_output(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)
        pid = self.assert_command(["list"], stderr='')
        format_kwargs = dict(system_name=self.infinipy.get_name(), system_serial=self.infinipy.get_serial(),
                             pool_name=pool.get_name(), pool_id=pool.get_id())
        self.assertEquals(EXPECTED_OUTPUT.format(**format_kwargs).lstrip(), pid.get_stdout())

    def test_system_list__password_changed(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)
        with patch("infinidat_openstack.scripts.get_infinipy_from_arguments", side_effect=Exception("error")):
            pid = self.assert_command(["list"], stderr='')
        format_kwargs = dict(system_name=self.infinipy.get_name(), pool_id=pool.get_id())
        self.assertEquals(EXPECTED_FAILURE.format(**format_kwargs).lstrip(), pid.get_stdout())
