from os import path
from time import sleep
from uuid import uuid4
from mock import MagicMock
from munch import Munch
from unittest import SkipTest
from infi.execute import execute_assert_success, execute
from infi.pyutils.lazy import cached_function
from infi.pyutils.contexts import contextmanager
from infi.pyutils.retry import retry_func, WaitAndRetryStrategy
from infi.vendata.integration_tests import TestCase
from infi.vendata.smock import HostMock
from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver, volume_opts
from infinidat_openstack import config, scripts


CINDER_LOG_FILE = "/var/log/cinder/volume.log"

@cached_function
def prepare_host():
    """using cached_function to make sure this is called only once"""
    # we will be using single paths, in the tests for now, so no need to spend time on configuring multipath
    # execute(["bin/infinihost", "settings", "check", "--auto-fix"])
    execute(["yum", "reinstall", "-y", "python-setuptools"])
    execute(["yum", "install",   "-y", "python-devel"])
    execute(["easy_install-2.6", "-U", "requests"])
    execute(["python2.6", "setup.py", "install"])


def get_cinder_client(host="localhost"):
    from cinderclient.v1 import client
    return client.Client("admin", "admin", "admin", "http://{}:5000/v2.0/".format(host), service_type="volume")


def restart_cinder():
    execute_assert_success(["openstack-service", "restart", "cinder-volume"])
    sleep(10) # give time for the volume drive to come up, no APIs to checking this


def get_cinder_log():
    with open(CINDER_LOG_FILE) as fd:
        return fd.read()


class NotReadyException(Exception):
    pass


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
    def provisioning_pool_context(self):
        pool = self.infinipy.types.Pool.create(self.infinipy)
        with self.cinder_context(self.infinipy, pool):
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

    def wait_for_object_creation(self, cinder_object, timeout=5):
        @retry_func(WaitAndRetryStrategy(timeout, 1))
        def poll():
            if cinder_object.status in ("creating", ):
                cinder_object.get()
                raise NotReadyException(cinder_object.id, cinder_object.status)
        poll()

    def create_volume(self, size_in_gb, pool=None, timeout=30):
        volume_type = None if pool is None else "{}/{}".format(self.infinipy.get_name(), pool.get_name())
        cinder_volume = self.get_cinder_client().volumes.create(size_in_gb, volume_type=volume_type)
        if timeout:
            self.wait_for_object_creation(cinder_volume, timeout=timeout)
        self.assertIn(cinder_volume.status, ("available", ))
        return cinder_volume

    @contextmanager
    def cinder_volume_context(self, size_in_gb, pool=None, timeout=30):
        cinder_volume = self.create_volume(size_in_gb, pool, timeout)
        yield cinder_volume
        self.get_cinder_client().volumes.delete(cinder_volume)

    @contextmanager
    def cinder_mapping_context(self, cinder_volume):
        from socket import gethostname
        from infi.hbaapi import get_ports_collection
                   #          pass
                   #      connector={u'ip': u'172.16.86.169', u'host': u'openstack01', u'wwnns': [u'20000000c99115ea'],
                   # u'initiator': u'iqn.1993-08.org.debian:01:1cef2344a325', u'wwpns': [u'10000000c99115ea']}
        fc_ports = get_ports_collection().get_ports()
        connector = dict(initiator='iqn.sometthing:0102030405060708',
                         host=gethostname(), ip='127.0.0.1',
                         wwns=[port.node_wwn for port in fc_ports], wwpns=[port.port_wwn for port in fc_ports])
        connection = cinder_volume.initialize_connection(cinder_volume, connector)
        yield connection
        cinder_volume.terminate_connection(cinder_volume, connector)


class RealTestCaseMixin(object):
    get_cinder_client = staticmethod(get_cinder_client)

    @classmethod
    def setup_host(cls):
        if not path.exists("/usr/bin/cinder"):
            raise SkipTest("openstack not installed")
        with config.get_config_parser(write_on_exit=True) as config_parser:
            config.set_enabled_backends(config_parser, [])
            for section in config.get_infinibox_sections(config_parser):
                config_parser.remove_section(section)
        prepare_host()

    @classmethod
    def teardown_host(cls):
        prepare_host()

    @classmethod
    def setup_infinibox(cls):
        cls.system = cls.system_factory.allocate_infinidat_system()
        cls.infinipy = cls.system.get_infinipy()
        cls.infinipy.purge()

    @classmethod
    def zone_localhost_with_infinibox(cls):
        cls.zoning.purge_all_related_zones()
        cls.zoning.zone_host_with_system__single_path(cls.system)

    @classmethod
    def teardown_infinibox(cls):
        try:
            cls.system.release()
        except:
            pass

    @contextmanager
    def cinder_context(self, infinipy, pool):
        with config.get_config_parser(write_on_exit=True) as config_parser:
            key = config.apply(config_parser, self.infinipy.get_name(), pool.get_name(), "infinidat", "123456")
            config.enable(config_parser, key)
            config.update_volume_type(self.get_cinder_client(), key, self.infinipy.get_name(), pool.get_name())
        restart_cinder()
        before = get_cinder_log()
        try:
            yield
        finally:
            after = get_cinder_log()
            print after.replace(before, '')
            with config.get_config_parser(write_on_exit=True) as config_parser:
                # config.delete_volume_type(self.get_cinder_client(), key)
                config.disable(config_parser, key)
            restart_cinder()


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
        cls.apply_cinder_patches()

    @classmethod
    def zone_localhost_with_infinibox(cls):
        cls.smock.get_inventory().zone_with_system__full_mesh(cls.infinipy)

    @classmethod
    @contextmanager
    def cinder_context(cls, infinipy, pool):
        volume_driver_config = Munch(**{item.name: item.default for item in volume_opts})
        volume_driver_config.update(san_ip=infinipy.get_hostname(),
                                    infinidat_pool_id=pool.get_id(),
                                    san_login="infinidat", san_password="123456")
        volume_driver_config.append_config_values = lambda values: None
        volume_driver_config.safe_get = lambda key: volume_driver_config.get(key, None)
        volume_driver = InfiniboxVolumeDriver(configuration=volume_driver_config)
        volume_drive_context = Munch()
        volume_driver.do_setup(cls.cinder_context)
        volume_type = "{}/{}".format(infinipy.get_name(), pool.get_name())
        cls.volume_driver_by_type[volume_type] = volume_driver
        yield

    @classmethod
    def apply_cinder_patches(cls):
        def create(size, volume_type=None):
            volume_type = cls.volume_driver_by_type.keys()[0] if volume_type is None else volume_type

            cinder_volume = Munch(size=size, id=str(uuid4()), status='available', display_name=None)
            cinder_volume.volume_type = volume_type
            cinder_volume.initialize_connection = initialize_connection
            cinder_volume.terminate_connection = terminate_connection

            cls.volume_driver_by_type[volume_type].create_volume(cinder_volume)
            return cinder_volume

        def volume_types__findall():
            volume_types = []
            for key, value in cls.volume_driver_by_type.items():
                mock = MagicMock()
                mock.name = key
                mock.get_keys.return_value = dict(volume_backend_name=value.get_volume_stats()["volume_backend_name"])
                volume_types.append(mock)
            return volume_types

        def initialize_connection(cinder_volume, connector):
            from infi.storagemodel import get_storage_model
            cls.volume_driver_by_type[cinder_volume.volume_type].initialize_connection(cinder_volume, connector)
            get_storage_model().refresh()

        def terminate_connection(cinder_volume, connector):
            from infi.storagemodel import get_storage_model
            cls.volume_driver_by_type[cinder_volume.volume_type].terminate_connection(cinder_volume, connector)
            get_storage_model().refresh()

        cls.get_cinder_client().volumes.create.side_effect = create
        cls.get_cinder_client().volume_types.findall = volume_types__findall

    @classmethod
    def teardown_infinibox(cls):
        pass
