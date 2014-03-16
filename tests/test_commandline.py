from infi.execute import execute_assert_success
from infi.unittest import TestCase, SkipTest
from shutil import copy
from os import path


class CommandlineTestsMixin(object):
    def test_system_list(self):
        pid = self.assert_command(["list"], stderr='')
        self.assertIn("---------", pid.get_stdout())

    def test_set(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        args = ["set", self.infinipy.get_name(), pool.get_name(), "infinidat", "123456"]
        stderr = 'done, restarting cinder-volume service is requires for changes to take effect\n'
        pid = self.assert_command(args, stderr=stderr)

    def assert_command(self, args, stderr=None):
        pid = self.execute(args)
        if stderr is not None:
            self.assertEquals(pid.get_stderr(), stderr)
        return pid

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


class RealTestCase(TestCase, CommandlineTestsMixin):
    EXECUTABLE = "/usr/bin/openstack-infinibox-config"

    @classmethod
    def setUpClass(cls):
        if not path.exists(cls.EXECUTABLE):
            raise SkipTest("openstack plugin not installed")
        cls.setup_infinibox()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_infinibox()

    def execute(self, args):
        return execute_assert_success([self.EXECUTABLE] + args)


class MockTestCase(TestCase, CommandlineTestsMixin):
    EXECUTABLE = "bin/openstack-infinibox-config"
    CONFIG_FILE = "tests/conf/commandline_tests.conf"
    RC_FILE = "tests/conf/commandline_tests.rc"

    @classmethod
    def setUpClass(cls):
        copy("tests/conf/empty.conf", cls.CONFIG_FILE)
        cls.setup_infinibox()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_infinibox()


    def execute(self, args):
        defaults = [self.EXECUTABLE, "--dry-run",
                    "--config-file={}".format(self.CONFIG_FILE), "--rc-file={}".format(self.RC_FILE)]
        return execute_assert_success(defaults + args)
