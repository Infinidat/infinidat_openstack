from unittest import TestCase, SkipTest
from infinidat_openstack import config
from shutil import copy

class ConfigTestCase(TestCase):
    def test_empty_config_file(self):
        with config.get_config_parser("tests/conf/empty.conf") as config_parser:
            self.assertEquals(config.get_systems(config_parser), list())
            self.assertEquals(config.get_enabled_backends(config_parser), list())

    def test_config_file_with_one_system(self):
        box = {'address': '1.2.3.4', 'password': 'password', 'pool': 'pool', 'username': 'login', 'key': 'foobar'}
        with config.get_config_parser("tests/conf/one.conf") as config_parser:
            self.assertEquals(config.get_systems(config_parser), [box])
            self.assertEquals(config.get_enabled_backends(config_parser), ["foobar"])

    def test_adding_one_pool(self):
        box = {'address': '1.2.3.4', 'password': 'password', 'pool': 'pool', 'username': 'login'}
        src, dst = "tests/conf/empty.conf", "tests/conf/adding_box.conf"
        copy(src, dst)
        with config.get_config_parser("tests/conf/adding_box.conf", True) as config_parser:
            self.assertEquals(config.get_enabled_backends(config_parser), list())
            config.apply(config_parser, **box)
        with config.get_config_parser("tests/conf/adding_box.conf") as config_parser:
            self.assertEquals(config.get_enabled_backends(config_parser), ["1.2.3.4/pool"])

    def test_adding_two_pools(self):
        raise SkipTest("not implemented")

    def test_adding_two_pools_from_different_systems(self):
        raise SkipTest("not implemented")

    def test_backup(self):
        raise SkipTest("not implemented")

    def test_saving_does_not_fuck_up_the_defaults(self):
        raise SkipTest("not implemented")

    def test_saving_does_not_fuck_up_other_sections(self):
        raise SkipTest("not implemented")

    def test_saving_deletes_comments(self):
        raise SkipTest("not implemented")

    def test_enable(self):
        raise SkipTest("not implemented")

    def test_disable(self):
        raise SkipTest("not implemented")
