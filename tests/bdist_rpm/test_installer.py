from os import remove, path
from unittest import TestCase, SkipTest
from infi.pyutils.contexts import contextmanager
from infi.execute import execute_assert_success


class InstallerTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        if not path.exists("/usr/bin/cinder"):
            raise SkipTest("openstack not installed")
        execute_assert_success(["yum", "install", "-y", "python-devel"])
        execute_assert_success(["rm", "-rf", "dist"])

    def test_package_installation(self):
        package = self.build()
        self.addCleanup(remove, package)
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

    def is_product_installed(self):
        return "infinidat_openstack" in execute_assert_success(["rpm", "-qa"]).get_stdout()

    def build(self):
        from build import shorten_version
        from glob import glob
        import infinidat_openstack.__version__
        execute_assert_success(["bin/python", "tests/bdist_rpm/build.py"])
        reload(infinidat_openstack.__version__)
        short_version = shorten_version(infinidat_openstack.__version__.__version__)
        return glob("dist/infinidat_openstack-{0}-*.rpm".format(short_version))[0]

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

    def assert_volume_driver_importable(self):
        execute_assert_success(["/usr/bin/python", "-c", "from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver"])

    def assert_commandline_tool_works(self):
        execute_assert_success(["/usr/bin/infini-openstack", "volume-backend", "list"])

    def build_two_packages(self):
        first = self.build()
        execute_assert_success(["git", "commit", "--allow-empty", "--message", "testing package upgrade"])
        def _revert():
            execute_assert_success(["git", "reset", "--hard", "HEAD^"])
            execute_assert_success(["bin/buildout", "buildout:develop=", "install", "setup.py", "__version__.py"])
        self.addCleanup(_revert)
        second = self.build()
        return first, second
