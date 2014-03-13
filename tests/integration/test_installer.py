from unittest import TestCase, SkipTest

class InstallerTestCase(TestCase):
    def test_package_installation(self):
        # with self.assert_not_installed_context():
        #     package = self.build()
        #     with self.install_context(package):
        #         self.assert_package_installed(package)
        #         self.assert_volume_driver_importable()
        #         self.assert_commandline_tool_works()
        raise SkipTest("not implemented")

    def test_package_upgrade(self):
        # with self.assert_not_installed_context():
        #     old_package = self.build()
        #     with self.install_context(old_package):
        #         self.assert_package_installed(package)
        #         self.bump_version()
        #         new_package = self.build()
        #         with self.upgrade_context(new_package):
        #             self.assert_package_installed(package)
        #             self.assert_volume_driver_importable()
        #             self.assert_commandline_tool_works()
        raise SkipTest("not implemented")
