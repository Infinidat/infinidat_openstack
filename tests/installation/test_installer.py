from os import path
from unittest import TestCase, SkipTest
from infi.pyutils.contexts import contextmanager
from infi.execute import execute_assert_success
from infi.os_info import get_platform_string
from logging import getLogger


logger = getLogger(__name__)


def shorten_version(long_version):
    from infi.os_info import shorten_version_string
    return shorten_version_string(long_version)


class InstallerMixin(object):
    def test_package_installation(self):
        package = self.build()
        with self.assert_not_installed_context():
            with self.install_context(package):
                self.assert_package_installed(package)
                self.assert_volume_driver_importable()
                self.assert_commandline_tool_works()

    def test_package_upgrade(self):
        first, second = self.build_two_packages()
        self.assertNotEquals(first, second)
        with self.assert_not_installed_context():
            with self.install_context(first):
                self.assert_package_installed(first)
                with self.upgrade_context(second):
                    self.assert_package_installed(second)
                    self.assert_volume_driver_importable()
                    self.assert_commandline_tool_works()

    @contextmanager
    def assert_not_installed_context(self):
        self.assertFalse(self.is_product_installed())
        yield
        self.assertFalse(self.is_product_installed())

    def assert_volume_driver_importable(self):
        execute_assert_success(["/usr/bin/python", "-c", "from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver"])

    def assert_commandline_tool_works(self):
        execute_assert_success(["/usr/bin/infini-openstack", "volume-backend", "list"])

    def build_two_packages(self):
        first = self.build()
        execute_assert_success(["git", "commit", "--allow-empty", "--message", "testing package upgrade"])
        execute_assert_success(["bin/buildout", "buildout:develop=", "install", "setup.py", "__version__.py"])
        def _revert():
            execute_assert_success(["git", "reset", "--hard", "HEAD^"])
            execute_assert_success(["bin/buildout", "buildout:develop=", "install", "setup.py", "__version__.py"])
        self.addCleanup(_revert)
        second = self.build()
        return first, second


class RPMTestCase(TestCase, InstallerMixin):
    @classmethod
    def setUpClass(cls):
        if not path.exists("/usr/bin/cinder"):
            raise SkipTest("openstack not installed")
        if 'centos' not in get_platform_string() and 'redhat' not in get_platform_string():
            raise SkipTest("not centos or redhat")
        execute_assert_success(["yum", "install", "-y", "python-devel"])
        execute_assert_success(["rm", "-rf", "dist"])

    def build(self):
        from glob import glob
        import infinidat_openstack.__version__
        command = ["bin/python", "tests/bdist_rpm/build.py"]
        logger.info("running {}".format(command))
        pid = execute_assert_success(command)
        logger.info("output: {}".format(pid.get_stdout()))
        reload(infinidat_openstack.__version__)
        short_version = shorten_version(infinidat_openstack.__version__.__version__)
        all_packages = glob("dist/*rpm")
        res = glob("dist/infinidat_openstack-{0}-*.rpm".format(short_version))[0]
        return res

    def is_product_installed(self):
        return "infinidat_openstack" in execute_assert_success(["rpm", "-qa"]).get_stdout()

    @contextmanager
    def install_context(self, package):
        execute_assert_success(["rpm", "-Uvh", package])
        try:
            yield
        finally:
            execute_assert_success(["rpm", "-e", "infinidat_openstack"])

    @contextmanager
    def upgrade_context(self, package):
        execute_assert_success(["rpm", "-Uvh", package])
        yield

    def assert_package_installed(self, package):
        result = execute_assert_success(["rpm", "-q", "infinidat_openstack", "--queryformat=%{version}\n"])
        self.assertIn(package.split("-")[1], result.get_stdout().splitlines())


class DEBTestCase(TestCase, InstallerMixin):
    @classmethod
    def setUpClass(cls):
        if not path.exists("/opt/stack"):
            raise SkipTest("devstack not installed")
        if 'ubuntu' not in get_platform_string():
            raise SkipTest("not ubuntu")
        execute_assert_success("apt-get install -y python-all python-all-dev python-setuptools debhelper".split(' '))
        execute_assert_success("/usr/bin/easy_install -U setuptools".split(' '))
        execute_assert_success("/usr/bin/easy_install -U stdeb".split(' '))
        execute_assert_success(["rm", "-rf", "dist"])

    def build(self):
        from glob import glob
        import infinidat_openstack.__version__
        command = "PATH=/usr/bin:$PATH bin/python tests/bdist_deb/build.py"
        logger.info("running {}".format(command))
        pid = execute_assert_success(command, shell=True)
        logger.info("output: {}".format(pid.get_stdout()))
        reload(infinidat_openstack.__version__)
        all_packages = glob("parts/*deb")
        res = glob("parts/python-infinidat-openstack_{0}-*.deb".format(infinidat_openstack.__version__.__version__))[0]
        return res

    def is_product_installed(self):
        return "python-infinidat-openstack" in execute_assert_success(["dpkg", "-l"]).get_stdout()

    @contextmanager
    def install_context(self, package):
        from glob import glob
        non_infinidat_packages = [i for i in glob("parts/*deb") if "python-infinidat-openstack" not in i]
        execute_assert_success(["dpkg", "-i", package] + non_infinidat_packages)
        try:
            yield
        finally:
            execute_assert_success(["dpkg", "-r", "python-infinidat-openstack"])

    @contextmanager
    def upgrade_context(self, full_path):
        execute_assert_success(["dpkg", "-i", full_path])
        yield

    def assert_package_installed(self, package):
        result = execute_assert_success(["dpkg", "-l", "python-infinidat-openstack"]).get_stdout()
        self.assertIn(path.basename(package).split('_')[0].split('-')[0], result)
