from infi.pyutils.lazy import cached_function
from infi.vendata.integration_tests import TestCase
from infinidat_openstack import config, scripts
from infi.execute import execute_assert_success
from infi.pyutils.contexts import contextmanager


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
    get_cinder_client = staticmethod(get_cinder_client)
    config = config

    @classmethod
    def setUpClass(cls):
        super(OpenStackTestCase, self).setUpClass()
        cls.system = cls.system_factory.allocate_infinidat_system()
        cls.infinipy = cls.system.get_infinipy()
        cls.infinipy.purge()
        try:
            cls.zoning.purge_all_related_zones()
            cls.zoning.zone_host_with_system__full_mesh(cls.system)
        except:
            cls.system.release()
            raise

    @contextmanager
    def provisioning_pool_context(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        with config.get_config_parser(write_on_exit=True) as config_parser:
            key = config.apply(config_parser, system.get_fqdn(), pool, "infinidat", "123456")
            config.enable(config_parser, key)
            scripts.restart_cinder()
        try:
            yield pool
        finally:
            with config.get_config_parser(write_on_exit=True) as config_parser:
                config.disable(config_parser, key)
                scripts.restart_cinder()

    @contextmanager
    def assert_volume_count(self, diff):
        before = self.system.get_infinipy().get_volumes()
        lambda now: self.system.get_infinipy().get_volumes()
        lambda func: [volume for volume in now() if volume not in before], \
                     [volume for volume in before if volume not in now()]
        yield func
        after = now()
        self.assertEquals(len(after), len(before)+diff)

    def test_create_volume_in_one_pool(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count(1) as get_diff:
                self.get_cinder_client().volumes.create(1)# create volume via cinder
                [volume], _ = get_diff()
