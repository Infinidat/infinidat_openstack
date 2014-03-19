from unittest import TestCase, SkipTest
from infinidat_openstack import config
from shutil import copy
from mock import patch, Mock
from os import path


class ConfigTestCase(TestCase):
    def test_empty_config_file(self):
        with config.get_config_parser("tests/conf/empty.conf") as config_parser:
            self.assertEquals(config.get_systems(config_parser), list())
            self.assertEquals(config.get_enabled_backends(config_parser), list())

    def test_config_file_with_one_system(self):
        box = {'address': '1.2.3.4', 'password': 'password', 'pool_id': 1, 'username': 'login',
               'key': 'infinibox-1-pool-1'}
        with config.get_config_parser("tests/conf/one.conf") as config_parser:
            self.assertEquals(config.get_systems(config_parser), [box])
            self.assertEquals(config.get_enabled_backends(config_parser), ["foobar"])

    def prepare_conf(self, filepath, src="tests/conf/empty.conf"):
        copy(src, filepath)

    def test_adding_one_pool(self, filepath="tests/conf/adding_box.conf"):
        kwargs = {'address': '1.2.3.4', 'password': 'password', 'pool_name': 'pool', 'username': 'login'}
        box = {'address': '1.2.3.4', 'password': 'password', 'pool_id': 1, 'username': 'login',
               'key': 'infinibox-1-pool-1'}
        self.prepare_conf(filepath)
        with config.get_config_parser(filepath, True) as config_parser:
            self.assertEquals(config.get_enabled_backends(config_parser), list())
            with patch("infinipy.System") as System:
                System().get_serial.return_value = 1
                System().get_version.return_value = '1.5'
                pool = Mock()
                pool.get_id.return_value = 1
                System().objects.Pool.find.return_value = [pool]
                key = config.apply(config_parser, **kwargs)
            config.disable(config_parser, key)
            config.enable(config_parser, key)
        with config.get_config_parser(filepath) as config_parser:
            self.assertEquals(config.get_enabled_backends(config_parser), ["infinibox-1-pool-1"])

    def test_adding_two_pools(self, filepath="tests/conf/adding_two_boxes.conf"):
        kwargs = {'address': '1.2.3.4', 'password': 'password', 'pool_name': 'pool', 'username': 'login'}
        box = {'address': '1.2.3.4', 'password': 'password', 'pool_id': 1, 'username': 'login',
               'key': 'infinibox-1-pool-1'}
        self.prepare_conf(filepath)
        with config.get_config_parser(filepath, True) as config_parser:
            self.assertEquals(config.get_enabled_backends(config_parser), list())
            with patch("infinipy.System") as System:
                System().get_serial.return_value = 1
                System().get_version.return_value = '1.5'
                pool = Mock()
                pool.get_id.return_value = 1
                System().objects.Pool.find.return_value = [pool]
                key = config.apply(config_parser, **kwargs)
                config.enable(config_parser, key)
            with patch("infinipy.System") as System:
                System().get_serial.return_value = 1
                System().get_version.return_value = '1.5'
                pool = Mock()
                pool.get_id.return_value = 2
                System().objects.Pool.find.return_value = [pool]
                kwargs['pool_name'] = 'pool2'
                key = config.apply(config_parser, **kwargs)
                config.enable(config_parser, key)
        with config.get_config_parser(filepath) as config_parser:
            self.assertEquals(len(config.get_systems(config_parser)), 2)
            self.assertEquals(len(config.get_enabled_backends(config_parser)), 2)
            config.disable(config_parser, key)
            self.assertEquals(len(config.get_enabled_backends(config_parser)), 1)

    def test_adding_pool_that_was_renamed(self, filepath="tests/conf/adding_after_pool_rename.conf"):
        kwargs = {'address': '1.2.3.4', 'password': 'password', 'pool_name': 'pool', 'username': 'login'}
        box = {'address': '1.2.3.4', 'password': 'password', 'pool_id': 1, 'username': 'login',
               'key': 'infinibox-1-pool-1'}
        self.prepare_conf(filepath)
        with config.get_config_parser(filepath, True) as config_parser:
            self.assertEquals(config.get_enabled_backends(config_parser), list())
            with patch("infinipy.System") as System:
                System().get_serial.return_value = 1
                System().get_version.return_value = '1.5'
                pool = Mock()
                pool.get_id.return_value = 1
                System().objects.Pool.find.return_value = [pool]
                key = config.apply(config_parser, **kwargs)
                config.enable(config_parser, key)
            with patch("infinipy.System") as System:
                System().get_serial.return_value = 1
                System().get_version.return_value = '1.5'
                pool = Mock()
                pool.get_id.return_value = 1
                System().objects.Pool.find.return_value = [pool]
                kwargs['pool_name'] = 'pool2'
                key = config.apply(config_parser, **kwargs)
                config.enable(config_parser, key)
        with config.get_config_parser(filepath) as config_parser:
            self.assertEquals(len(config.get_systems(config_parser)), 1)
            self.assertEquals(len(config.get_enabled_backends(config_parser)), 1)

    def test_adding_two_pools_from_different_systems(self, filepath="tests/conf/two_pools_from_different_systems.conf"):
        kwargs = {'address': '1.2.3.4', 'password': 'password', 'pool_name': 'pool', 'username': 'login'}
        box = {'address': '1.2.3.4', 'password': 'password', 'pool_id': 1, 'username': 'login',
               'key': 'infinibox-1-pool-1'}
        self.prepare_conf(filepath)
        with config.get_config_parser(filepath, True) as config_parser:
            self.assertEquals(config.get_enabled_backends(config_parser), list())
            with patch("infinipy.System") as System:
                System().get_serial.return_value = 1
                System().get_version.return_value = '1.5'
                pool = Mock()
                pool.get_id.return_value = 1
                System().objects.Pool.find.return_value = [pool]
                key = config.apply(config_parser, **kwargs)
                config.enable(config_parser, key)
            with patch("infinipy.System") as System:
                System().get_serial.return_value = 2
                System().get_version.return_value = '1.5'
                pool = Mock()
                pool.get_id.return_value = 2
                System().objects.Pool.find.return_value = [pool]
                kwargs['pool_name'] = 'pool2'
                key = config.apply(config_parser, **kwargs)
                config.enable(config_parser, key)
        with config.get_config_parser(filepath) as config_parser:
            self.assertEquals(len(config.get_systems(config_parser)), 2)
            self.assertEquals(len(config.get_enabled_backends(config_parser)), 2)
            config.disable(config_parser, key)
            self.assertEquals(len(config.get_enabled_backends(config_parser)), 1)

    def test_backup(self, filepath="tests/conf/testing_backup.conf"):
        from glob import glob
        from os import remove
        [remove(path) for path in glob(filepath + ".*")]
        self.prepare_conf(filepath, "tests/conf/one.conf")
        with open(filepath) as fd:
            before = fd.read()
        with config.get_config_parser(filepath, True) as config_parser:
            config.remove(config_parser, key="infinibox-1-pool-1'")
        with open(filepath+".1") as fd:
            backup = fd.read()
        with open(filepath) as fd:
            after = fd.read()
        self.assertNotEquals(before, after)
        self.assertEquals(before, backup)

    def test_saving_does_not_fuck_up_the_defaults(self, filepath="tests/conf/empty_copy.conf"):
        self.prepare_conf(filepath)
        with config.get_config_parser(filepath, True) as config_parser:
            before = config_parser.get("DEFAULT", "sql_idle_timeout")
        with config.get_config_parser(filepath) as config_parser:
            after = config_parser.get("DEFAULT", "sql_idle_timeout")
        self.assertEquals(before, "3600")
        self.assertEquals(before, after)

    def test_saving_deletes_comments(self, filepath="tests/conf/empty_copy.conf"):
        self.prepare_conf(filepath)
        with open(filepath) as fd:
            before = fd.read()
        with config.get_config_parser(filepath, True) as config_parser:
            pass
        with open(filepath) as fd:
            after = fd.read()
        self.assertIn("#", before)
        self.assertNotIn("#", after)
