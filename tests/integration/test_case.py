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


VOLUME_LOG_FILE = "/var/log/cinder/volume.log"
CINDER_VOLUME_LOG_FILE = "/var/log/cinder/cinder-volume.log"

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


def get_volume_log():
    with open(VOLUME_LOG_FILE) as fd:
        return fd.read()


def get_cinder_volume_log():
    with open(CINDER_VOLUME_LOG_FILE) as fd:
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
        pool.purge()

    @contextmanager
    def assert_volume_count(self, diff=0):
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

    def wait_for_object_deletion(self, cinder_object, timeout=5):
        from cinderclient.exceptions import NotFound

        @retry_func(WaitAndRetryStrategy(timeout, 1))
        def poll():
            try:
                cinder_object.get()
            except NotFound:
                return
            else:
                raise NotReadyException(cinder_object.id, cinder_object.status)

        poll()

    def _create_volume(self, size_in_gb, volume_type=None, source_volid=None, timeout=30):
        cinder_volume = self.get_cinder_client().volumes.create(size_in_gb,
                                                                volume_type=volume_type, source_volid=source_volid)
        if timeout:
            self.wait_for_object_creation(cinder_volume, timeout=timeout)
        self.assertIn(cinder_volume.status, ("available", ))
        return cinder_volume

    def create_volume(self, size_in_gb, pool=None, timeout=30):
        volume_type = None if pool is None else "[InfiniBox] {}/{}".format(self.infinipy.get_name(), pool.get_name())
        return self._create_volume(size_in_gb, volume_type=volume_type, timeout=timeout)

    def create_snapshot(self, cinder_volume, timeout=30):
        cinder_snapshot = self.get_cinder_client().volume_snapshots.create(cinder_volume.id)
        if timeout:
            self.wait_for_object_creation(cinder_snapshot, timeout=timeout)
        self.assertIn(cinder_volume.status, ("available", ))
        return cinder_snapshot

    def create_clone(self, cinder_volume, timeout=30):
        cinder_clone = self._create_volume(cinder_volume.size, timeout=timeout,
                                           volume_type=cinder_volume.volume_type, source_volid=cinder_volume.id)
        return cinder_clone

    def delete_cinder_object(self, cinder_object, timeout=30):
        cinder_object.delete()
        if timeout:
            self.wait_for_object_deletion(cinder_object, timeout=timeout)

    @contextmanager
    def cinder_volume_context(self, size_in_gb, pool=None, timeout=30):
        cinder_volume = self.create_volume(size_in_gb, pool, timeout)
        yield cinder_volume
        self.delete_cinder_object(cinder_volume)

    @contextmanager
    def cinder_mapping_context(self, cinder_volume):
        from socket import gethostname
        from infi.hbaapi import get_ports_collection
        fc_ports = get_ports_collection().get_ports()
        connector = dict(initiator='iqn.sometthing:0102030405060708',
                         host=gethostname(), ip='127.0.0.1',
                         wwns=[str(port.node_wwn) for port in fc_ports], wwpns=[str(port.port_wwn) for port in fc_ports])
        connection = cinder_volume.initialize_connection(cinder_volume, connector)
        yield connection
        cinder_volume.terminate_connection(cinder_volume, connector)

    @contextmanager
    def cinder_snapshot_context(self, cinder_volume, timeout=30):
        cinder_snapshot = self.create_snapshot(cinder_volume, timeout)
        yield cinder_snapshot
        self.delete_cinder_object(cinder_snapshot, timeout)

    @contextmanager
    def cinder_clone_context(self, cinder_volume, timeout=30):
        cinder_clone = self.create_clone(cinder_volume, timeout)
        yield cinder_clone
        self.delete_cinder_object(cinder_clone, timeout)


class RealTestCaseMixin(object):
    get_cinder_client = staticmethod(get_cinder_client)

    @classmethod
    def cleanup_infiniboxes_from_cinder(cls):
        def cleanup_volume_types():
            cinder_client = cls.get_cinder_client()
            for volume_type in cinder_client.volume_types.findall():
                cinder_client.volume_types.delete(volume_type)

        def cleanup_volume_backends():
            with config.get_config_parser(write_on_exit=True) as config_parser:
                config.set_enabled_backends(config_parser, [])
                for section in config.get_infinibox_sections(config_parser):
                    config_parser.remove_section(section)
            restart_cinder()

        cleanup_volume_types()
        cleanup_volume_backends()

    @classmethod
    def setup_host(cls):
        if not path.exists("/usr/bin/cinder"):
            raise SkipTest("openstack not installed")
        prepare_host()
        cls.cleanup_infiniboxes_from_cinder()

    @classmethod
    def teardown_host(cls):
        prepare_host()

    @classmethod
    def setup_infinibox(cls):
        cls.system = cls.system_factory.allocate_infinidat_system()
        cls.infinipy = cls.system.get_infinipy()
        cls.infinipy.purge()
        cls.zone_localhost_with_infinibox()

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
    def volume_log_context(self):
        before = get_volume_log()
        try:
            yield
        finally:
            after = get_volume_log()
            print after.replace(before, '')

    @contextmanager
    def cinder_volume_log_context(self):
        before = get_cinder_volume_log()
        try:
            yield
        finally:
            after = get_cinder_volume_log()
            print after.replace(before, '')

    @contextmanager
    def cinder_context(self, infinipy, pool):
        with config.get_config_parser(write_on_exit=True) as config_parser:
            key = config.apply(config_parser, self.infinipy.get_name(), pool.get_name(), "infinidat", "123456")
            config.enable(config_parser, key)
            config.update_volume_type(self.get_cinder_client(), key, self.infinipy.get_name(), pool.get_name())
        restart_cinder()
        with self.volume_log_context(), self.cinder_volume_log_context():
            yield
        with config.get_config_parser(write_on_exit=True) as config_parser:
            config.delete_volume_type(self.get_cinder_client(), key)
            config.disable(config_parser, key)
            config.remove(config_parser, key)
        restart_cinder()


class MockTestCaseMixin(object):
    get_cinder_client = MagicMock()
    volume_driver_by_type = {}
    volumes = {}

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
        cls.zone_localhost_with_infinibox()

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
        volume_type = "[InfiniBox] {}/{}".format(infinipy.get_name(), pool.get_name())
        cls.volume_driver_by_type[volume_type] = volume_driver
        yield
        cls.volume_driver_by_type.pop(volume_type)

    @classmethod
    def apply_cinder_patches(cls):
        def get(cinder_object):
            from cinderclient.exceptions import NotFound
            if cinder_object.id in cls.volumes:
                return
            raise NotFound(cinder_object.id)

        def create(size, volume_type=None, source_volid=None):
            def delete(cinder_volume):
                cinder_volume.status = 'deleting'
                cls.volumes.pop(cinder_volume.id)
                volume_driver.delete_volume(cinder_volume)

            volume_type = cls.volume_driver_by_type.keys()[0] if volume_type is None else volume_type
            volume_driver = cls.volume_driver_by_type[volume_type]
            volume_id = str(uuid4())
            cinder_volume = cls.volumes.setdefault(volume_id, Munch(size=size, id=volume_id, status='available', display_name=None))
            cinder_volume.volume_type = volume_type
            cinder_volume.get = lambda *args, **kwargs: get(cinder_volume)
            cinder_volume.delete = lambda: delete(cinder_volume)
            cinder_volume.initialize_connection = initialize_connection
            cinder_volume.terminate_connection = terminate_connection
            cinder_volume.extend = extend
            cinder_volume.manager = Munch(extend=extend) # https://bugs.launchpad.net/python-cinderclient/+bug/1293423

            if source_volid is None: # new volume
                volume_driver.create_volume(cinder_volume)
            else: # new clone
                cinder_volume.source_volid = source_volid
                volume_driver.create_cloned_volume(cinder_volume, cls.volumes[source_volid])
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
            for item in connector["wwns"] + connector["wwpns"]:
                assert isinstance(item, basestring)
            cls.volume_driver_by_type[cinder_volume.volume_type].initialize_connection(cinder_volume, connector)
            get_storage_model().refresh()

        def terminate_connection(cinder_volume, connector):
            from infi.storagemodel import get_storage_model
            for item in connector["wwns"] + connector["wwpns"]:
                assert isinstance(item, basestring)
            cls.volume_driver_by_type[cinder_volume.volume_type].terminate_connection(cinder_volume, connector)
            get_storage_model().refresh()

        def extend(cinder_volume, new_size_in_gb):
            cls.volume_driver_by_type[cinder_volume.volume_type].extend_volume(cinder_volume, new_size_in_gb)

        def volume_snapshots__create(cinder_volume_id):
            def delete(cinder_snapshot):
                cinder_snapshot.status = 'deleting'
                cls.volumes.pop(cinder_snapshot.id)
                volume_driver.delete_snapshot(cinder_snapshot)

            snapshot_id = str(uuid4())
            source_cinder_volume = cls.volumes[cinder_volume_id]
            volume_driver = cls.volume_driver_by_type[source_cinder_volume.volume_type]
            cinder_snapshot = cls.volumes.setdefault(snapshot_id, Munch(id=snapshot_id, status='available', display_name=None, volume=source_cinder_volume))
            cinder_snapshot.get = lambda  *args, **kwargs: get(cinder_snapshot)
            cinder_snapshot.delete = lambda: delete(cinder_snapshot)
            volume_driver.create_snapshot(cinder_snapshot)
            return cinder_snapshot

        cls.get_cinder_client().volumes.create.side_effect = create
        cls.get_cinder_client().volume_snapshots.create = volume_snapshots__create
        cls.get_cinder_client().volume_types.findall = volume_types__findall


    @classmethod
    def teardown_infinibox(cls):
        pass
