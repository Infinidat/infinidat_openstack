from uuid import uuid4
from mock import MagicMock
from munch import Munch
from unittest import SkipTest
from infi.execute import execute_assert_success
from infi.pyutils.lazy import cached_function
from infi.pyutils.contexts import contextmanager
from infi.vendata.integration_tests import TestCase
from infi.vendata.smock import HostMock
from infinidat_openstack import config, scripts
from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver, volume_opts


@cached_function
def prepare_host():
    """using cached_function to make sure this is called only once"""
    from infi.execute import execute
    execute(["bin/infinihost", "settings", "check", "--auto-fix"])


def get_cinder_client(host="localhost"):
    from cinderclient.v1 import client
    return client.Client("admin", "admin", "admin", "http://{}:5000/v2.0/".format(host), service_type="volume")


def restart_cinder():
    execute_assert_success(["openstack-service", "restart", "openstack-cinder-volume"])


class OpenStackTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super(OpenStackTestCase, cls).setUpClass()
        cls.setup_host()
        cls.setup_infinibox()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_infinibox()
        cls.teardown_host()

    @contextmanager
    def provisioning_pool_context(self, volume_type=None):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        with self.cinder_context(self.infinipy, pool, volume_type):
            yield pool

    @contextmanager
    def assert_volume_count(self, diff):
        before = self.infinipy.get_volumes()
        now = lambda: self.infinipy.get_volumes()
        func = lambda: ([volume for volume in now() if volume not in before], \
                        [volume for volume in before if volume not in now()])
        yield func
        after = now()
        self.assertEquals(len(after), len(before)+diff)


class RealTestCaseMixin(object):
    get_cinder_client = staticmethod(get_cinder_client)
    config = config
    scripts = scripts

    @classmethod
    def setup_host(cls):
        from os import path
        if not path.exists("/usr/bin/cinder"):
            raise SkipTest("openstack not installed")
        prepare_host()

    @classmethod
    def teardown_host(cls):
        prepare_host()

    @classmethod
    def setup_infinibox(cls):
        cls.system = cls.system_factory.allocate_infinidat_system()
        cls.infinipy = cls.system.get_infinipy()
        cls.infinipy.purge()
        try:
            cls.zoning.purge_all_related_zones()
            cls.zoning.zone_host_with_system__full_mesh(cls.system)
        except:
            cls.system.release()
            raise

    @classmethod
    def teardown_infinibox(cls):
        try:
            cls.system.release()
        except:
            pass

    @contextmanager
    def cinder_context(self, infinipy, pool, volume_type=None):
        with self.config.get_config_parser(write_on_exit=True) as config_parser:
            key = self.config.apply(config_parser, self.infinipy.get_name(), pool.get_name(), "infinidat", "123456")
            self.config.enable(config_parser, key)
            self.scripts.restart_cinder()
        try:
            yield
        finally:
            with self.config.get_config_parser(write_on_exit=True) as config_parser:
                self.config.disable(config_parser, key)
                self.scripts.restart_cinder()


class MockTestCaseMixin(object):
    get_cinder_client = MagicMock()
    volume_driver_by_type = {}

    @classmethod
    def setup_host(cls):
        from capacity import GB
        cls.smock = HostMock()
        cls.smock.get_inventory().add_initiator()
        cls.smock_context = cls.smock.__enter__()
        configuration = Munch()

    @classmethod
    def teardown_host(cls):
        cls.smock.__exit__(None, None, None)

    @classmethod
    def _append_config_values(cls, values):
        pass

    @classmethod
    def setup_infinibox(cls):
        cls.infinipy = cls.smock.get_inventory().add_infinibox()
        cls.smock.get_inventory().zone_with_system__full_mesh(cls.infinipy)
        cls.apply_cinder_patches()

    @classmethod
    @contextmanager
    def cinder_context(cls, infinipy, pool, volume_type=None):
        volume_driver_config = Munch(**{item.name: item.default for item in volume_opts})
        volume_driver_config.update(san_ip=infinipy.get_hostname(),
                                    infinidat_pool=pool.get_name(),
                                    san_login="infinidat", san_password="123456")
        volume_driver_config.append_config_values = lambda values: None
        volume_driver_config.safe_get = lambda key: volume_driver_config.get(key, None)
        volume_driver = InfiniboxVolumeDriver(configuration=volume_driver_config)
        volume_drive_context = Munch()
        volume_driver.do_setup(cls.cinder_context)
        cls.volume_driver_by_type[volume_type] = volume_driver
        yield

    @classmethod
    def apply_cinder_patches(cls):
        def create(size, volume_type=None):
            cinder_volume = Munch(size=size, id=str(uuid4()))
            return cls.volume_driver_by_type[volume_type].create_volume(cinder_volume)

        cls.get_cinder_client().volumes.create.side_effect = create

    @classmethod
    def teardown_infinibox(cls):
        pass
