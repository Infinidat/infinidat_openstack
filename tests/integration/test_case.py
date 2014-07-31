from os import path
from time import sleep
from uuid import uuid4
from mock import MagicMock
from munch import Munch
from unittest import SkipTest
from urlparse import urlparse
from socket import gethostname, gethostbyname
from infi.execute import execute_assert_success, execute, execute_async
from infi.pyutils.lazy import cached_function
from infi.pyutils.contexts import contextmanager
from infi.pyutils.retry import retry_func, WaitAndRetryStrategy
from infi.vendata.integration_tests import TestCase
from infi.vendata.smock import HostMock
from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver, volume_opts
from infinidat_openstack import config, scripts


CINDER_LOGDIR = "/var/log/cinder"
KEYSTONE_LOGDIR = "/var/log/keystone"
CONFIG_FILE = path.expanduser(path.join('~', 'keystonerc_admin'))


@contextmanager
def logfile_context(logfile_path):
    with open(logfile_path) as fd:
        fd.read()
        try:
            yield
        finally:
            print '--- {} ---'.format(logfile_path)
            print fd.read()
            print '--- end ---'.format(logfile_path)


@contextmanager
def logs_context(logs_dir):
    from glob import glob
    glob_path = path.join(logs_dir, '*.log')
    contexts = [logfile_context(item) for item in glob(glob_path)]
    [context.__enter__() for context in contexts]
    try:
        yield
    finally:
        [context.__exit__(None, None, None) for context in contexts]


def fix_ip_addresses_in_openstack_keystone_database(regex):
    filename = 'mysql.dump'
    execute_assert_success("mysqldump keystone > {}".format(filename), shell=True)
    execute_assert_success("sed -ie {} {}".format(regex, filename), shell=True)
    execute_assert_success("mysql -u root -D keystone < {}".format(filename), shell=True)


def fix_ip_addresses_in_openstack():
    # openstack is shit; it wrote the IP address we got from the DHCP when installing it in a ton of configuration files
    # now that the IP address has changed, nothing is working anymore
    # so we need to find the new IP address, search-and-fucking-replace it in all the files
    # restart openatack and pray it will work
    with open(CONFIG_FILE) as fd:
        environment_text = fd.read()

    auth_url = scripts.parse_environment(environment_text)[-1]
    old_ip_address = urlparse(auth_url).netloc.split(':')[0]
    new_ip_address = gethostbyname(gethostname())

    execute_assert_success(['openstack-service', 'stop'])
    execute_assert_success(['rm', '-rf', '/var/log/*/*'])
    regex = "s/{}/{}/g".format(old_ip_address.replace('.', '\.'), new_ip_address)

    with open(CONFIG_FILE, 'w') as fd:
        fd.write(environment_text.replace(old_ip_address, new_ip_address))
    execute_assert_success('grep -rl {} /etc | xargs sed -ie {}'.format(old_ip_address, regex), shell=True)
    fix_ip_addresses_in_openstack_keystone_database(regex)

    execute(["pkill", "-9", "keystone"])
    with logs_context(KEYSTONE_LOGDIR):
        execute_assert_success(['openstack-service', 'start'])


@cached_function
def prepare_host():
    """using cached_function to make sure this is called only once"""
    execute(["bin/infinihost", "settings", "check", "--auto-fix"])
    fix_ip_addresses_in_openstack()
    execute(["yum", "reinstall", "-y", "python-setuptools"])
    execute(["yum", "install",   "-y", "python-devel"])
    execute(["easy_install-2.6", "-U", "requests"])
    execute(["python2.6", "setup.py", "install"])

    # This line actually installs the driver into openstack's python
    execute_assert_success(["python2.6", "setup.py", "install"])
    execute_assert_success(['openstack-service', 'restart'])


def get_cinder_client(host="localhost"):
    from cinderclient.v1 import client
    return client.Client("admin", "admin", "admin", "http://{}:5000/v2.0/".format(host), service_type="volume")


def restart_cinder():
    execute_assert_success(["openstack-service", "restart", "cinder-volume"])
    sleep(10) # give time for the volume drive to come up, no APIs to checking this


class NotReadyException(Exception):
    pass


class NoFCPortsException(Exception):
    pass


class OpenStackTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super(OpenStackTestCase, cls).setUpClass()
        cls.setup_infinibox()
        cls.setup_host()
        cls.zone_localhost_with_infinibox()

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
        connector = self.get_connector()
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

    def get_connector(self):
        raise NotImplementedError()


class RealTestCaseMixin(object):
    get_cinder_client = staticmethod(get_cinder_client)

    @classmethod
    def cleanup_infiniboxes_from_cinder(cls):
        def cleanup_volumes():
            cinder_client = cls.get_cinder_client()
            for volume in cinder_client.volumes.list():
                volume.delete()

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

        cleanup_volumes()
        cleanup_volume_types()
        cleanup_volume_backends()

    @classmethod
    def setup_host(cls):
        if not path.exists("/usr/bin/cinder"):
            raise SkipTest("openstack not installed")
        cls.cleanup_infiniboxes_from_cinder()

    @classmethod
    def teardown_host(cls):
        cls.cleanup_infiniboxes_from_cinder()

    @classmethod
    def setup_infinibox(cls):
        cls.system = cls.system_factory.allocate_infinidat_system(expiration_in_seconds=3600)
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
    def cinder_logs_context(self):
        with logs_context(CINDER_LOGDIR):
            yield

    @contextmanager
    def cinder_context(self, infinipy, pool):
        with config.get_config_parser(write_on_exit=True) as config_parser:
            key = config.apply(config_parser, self.infinipy.get_name(), pool.get_name(), "admin", "123456")
            config.enable(config_parser, key)
            config.update_volume_type(self.get_cinder_client(), key, self.infinipy.get_name(), pool.get_name())
        restart_cinder()
        with self.cinder_logs_context():
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
                                    san_login="admin", san_password="123456")
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


class OpenStackISCSITestCase(OpenStackTestCase):

    ISCSI_GW_SLEEP_TIME = 10

    def get_connector(self):
        return dict(initiator=OpenStackISCSITestCase.get_iscsi_initiator(),
                         host=gethostname(),
                         ip='127.0.0.1',
                         wwns=None,
                         wwpns=None)

    @classmethod
    def get_iscsi_initiator(cls):
        import re
        return re.findall('InitiatorName=(.+)', open('/etc/iscsi/initiatorname.iscsi').read())[0]

    @classmethod
    def setUpClass(cls):
        super(OpenStackISCSITestCase, cls).setUpClass()
        cls.install_iscsi_manager()
        cls.configure_iscsi_manager()
        cls.iscsi_manager_poll()
        cls.create_host_object_for_iscsi_client()
        cls.connect_to_iscsi_manager()
        cls.iscsi_manager_poll()

    @classmethod
    def tearDownClass(cls):
        cls.disconnect_from_iscsi_manager()
        cls.destroy_iscsi_manager_configuration()
        try:
            cls.host.delete()
        except:
            pass
        super(OpenStackISCSITestCase, cls).tearDownClass()

    @classmethod
    def create_host_object_for_iscsi_client(cls):
        def _int_to_16_bit_hex(n):
            return hex(n % (2**16-1))[2:].zfill(4)

        def _int_to_12_bit_wwn_format(n):
            return hex(n % (2**12-1))[2:].zfill(3)

        NPIV_64BIT_WWPN_TEMPLATE = "2{12bit_host_counter}{24bit_oui}{16bit_system_serial}{8bit_gateway_id}"
        INFINIDAT_OUI = "742b0f"

        node_id, port_id = cls.get_iscsi_port()
        gateway_id = str(node_id)+str(port_id)

        kwargs = {
            "12bit_host_counter": _int_to_12_bit_wwn_format(1),
              "24bit_oui": INFINIDAT_OUI,
              "16bit_system_serial": _int_to_16_bit_hex(cls.infinipy.get_serial()),
              "8bit_gateway_id": gateway_id
        }

        fc_port_string = NPIV_64BIT_WWPN_TEMPLATE.format(**kwargs)
        client_iqn = cls.get_iscsi_initiator()
        cls.host = cls.infinipy.objects.Host.create()
        cls.host.set_metadata("iscsi_manager_iqn", client_iqn)
        cls.host.add_fc_port(fc_port_string)

        # zone this new fc port with infinibox
        from infi.vendata.integration_tests.zoning import FcManager
        from infi.dtypes.wwn import WWN
        system_wwn = [wwn for wwn in cls.infinipy.get_fiber_target_addresses() if str(wwn)[-2:]== fc_port_string[-2:]][0]
        host_wwn = WWN(fc_port_string)
        FcManager().create_zone([host_wwn, system_wwn])

    @classmethod
    def connect_to_iscsi_manager(cls):
        execute(["iscsiadm", "-m", "discovery" , "-t" ,"sendtargets", "-p", gethostbyname(gethostname())])
        execute(["iscsiadm", "-m", "node" , "-L" ,"all"])

    @classmethod
    def disconnect_from_iscsi_manager(cls):
        execute(["iscsiadm", "-m", "node" , "-U" ,"all"])

    @classmethod
    def install_iscsi_manager(cls):
        execute(["curl http://iscsi-repo.lab.il.infinidat.com/setup | sudo sh -"], shell=True)
        execute(["yum", "install", "-y", "iscsi-manager"])
        execute(["yum", "install", "-y", "scst-2.6.32-431.17.1.el6.iscsigw.x86_64.x86_64"])
        execute(["yum", "install", "-y", "scstadmin.x86_64"])
        execute(["/etc/init.d/tgtd", "stop"])
        execute(["/etc/init.d/scst", "start"])
        execute(["yum", "install", "-y", "lsscsi"])

    @classmethod
    def configure_iscsi_manager(cls):
        cls.destroy_iscsi_manager_configuration()
        execute(["iscsi-manager", "config", "init"])
        execute(["iscsi-manager", "config", "set", "system", cls.infinipy.address_info.hostname, "infinidat", "123456"])
        node_id, port_id = cls.get_iscsi_port()
        execute(["iscsi-manager", "config", "add", "target", gethostbyname(gethostname()), str(node_id), str(port_id)])
        poll_script = """#!/bin/sh
        while true; do
            iscsi-manager poll
            sleep {}
        done
        """
        open("./iscsi-poll.sh", 'w').write(poll_script.format(cls.ISCSI_GW_SLEEP_TIME))
        execute(["chmod", "+x", "./iscsi-poll.sh"])
        execute_async(["sh", "./iscsi-poll.sh"])

    @classmethod
    def get_iscsi_port(cls):
        # TODO refactor using infi.stroagemodel
        import re
        sg_inq_output = execute(["""
            for i in `lsscsi | grep "NFINIDAT"| awk "{print $1}" | tr -d "[]"`;
            do  ls /sys/class/scsi_device/$i/device/scsi_generic ;
            done | while read line; do sg_inq -p 0x83 /dev/$line | grep "Relative target port:";
            done"""], shell=True).get_stdout()
        fc_ports = re.findall('\s*Relative target port: (0x.+)\s*', sg_inq_output)
        if not fc_ports:
            raise NoFCPortsException("Could not find any fc ports")

        # Assume only one port
        hex_port = int(fc_ports[0], 16)
        node_id = (hex_port >> 8) & 0xFF
        port_id = hex_port & 0xFF
        return node_id, port_id

    @classmethod
    def iscsi_manager_poll(cls):
        sleep(cls.ISCSI_GW_SLEEP_TIME)

    @classmethod
    def destroy_iscsi_manager_configuration(cls):
        execute(['pkill -f "sh ./iscsi-poll.sh"'], shell=True)
        execute(["rm", "-rf", "./iscsi-poll.sh"])
        execute(["killall", "iscsi-manager"])
        execute(["rm","-rf","./poll.lock"])
        cls.delete_npiv_ports_created_by_iscsi_manager()

    @classmethod
    def delete_npiv_ports_created_by_iscsi_manager(cls):
        import os
        FC_HOST_DIR = '/sys/class/fc_host'
        virtual_fc_hosts = [host for host in os.listdir(FC_HOST_DIR)
            if 'NPIV VPORT' in open(os.path.join(FC_HOST_DIR, host, 'port_type')).read()]
        physical_fc_host = [host for host in os.listdir(FC_HOST_DIR)
            if 'NPIV VPORT' not in open(os.path.join(FC_HOST_DIR, host, 'port_type')).read()][0]
        vport_delete_file_name = os.path.join(FC_HOST_DIR, physical_fc_host, 'vport_delete')
        for virtual_fc_host in virtual_fc_hosts:
            port_name = open(os.path.join(FC_HOST_DIR, virtual_fc_host, 'port_name')).read().strip().strip('0x')
            node_name = open(os.path.join(FC_HOST_DIR, virtual_fc_host, 'node_name')).read().strip().strip('0x')
            open(vport_delete_file_name,'w').write('{}:{}'.format(node_name, port_name))


class OpenStackFibreChannelTestCase(OpenStackTestCase):
    def get_connector(self):
        from infi.hbaapi import get_ports_collection
        fc_ports = get_ports_collection().get_ports()
        wwns = [str(port.port_wwn) for port in fc_ports]
        return dict(initiator=None,
                         host=gethostname(),
                         ip='127.0.0.1',
                         wwns=wwns,
                         wwpns=wwns)
