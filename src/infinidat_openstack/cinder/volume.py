from oslo.config import cfg
try:
    from cinder.openstack.common import log as logging
    from cinder.openstack.common.gettextutils import _ as translate
    from cinder.volume import driver
    from cinder import exception
except (ImportError, NameError):  # importing with just python hits NameErorr from the san module, the _ trick
    from .mock import logging, translate
    from . import mock as driver
    from . import mock as exception

from contextlib import contextmanager
from functools import wraps
from capacity import GiB
from time import sleep, time
from infi.pyutils.decorators import wraps

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('infinidat_pool_id', help='id the pool from which volumes are allocated', default=None),
    cfg.StrOpt('infinidat_provision_type', help='Provisioning type (thick or thin)', default='thick'),
    cfg.StrOpt('infinidat_volume_name_prefix', help='Cinder volume name prefix in Infinibox', default='openstack-vol'),
    cfg.StrOpt('infinidat_snapshot_name_prefix', help='Cinder snapshot name prefix in Infinibox',
               default='openstack-snap'),
    cfg.StrOpt('infinidat_host_name_prefix', help='Cinder host name prefix in Infinibox', default='openstack-host'),
    cfg.IntOpt('infinidat_iscsi_gw_timeout_sec', help='The time between polls in the iscsi manager', default=30),
    cfg.IntOpt('infinidat_iscsi_gw_time_between_retries_sec', help='Time between retries in our polling mechanism', default=1),
    cfg.IntOpt('infinidat_sync_sleep_duration', help='number of seconds to sleep after sync (workaround for cinder bug #1352875)', default=10),
    cfg.BoolOpt('infinidat_prefer_fc', help='Use wwpns from connector if supplied with iSCSI initiator', default=False),
    cfg.BoolOpt('infinidat_allow_pool_not_found', help='allow the driver initialization when the pool not found', default=False),
    cfg.BoolOpt('infinidat_purge_volume_on_deletion', help='allow the driver to purge a volume (delete mappings and snapshots if necessary)', default=False),
]

# Since we no longer inherit from SanDriver we have to read those config values
san_opts = [
        cfg.BoolOpt('san_thin_provision',
                    default=True,
                    help='Use thin provisioning for SAN volumes?'),
        cfg.StrOpt('san_ip',
                   default='',
                   help='IP address of SAN controller'),
        cfg.StrOpt('san_login',
                   default='admin',
                   help='Username for SAN controller'),
        cfg.StrOpt('san_password',
                   default='',
                   help='Password for SAN controller',
                   secret=True),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)
CONF.register_opts(san_opts)


SYSTEM_METADATA_VALUE = 'openstack'
STATS_VENDOR = 'Infinidat'
STATS_PROTOCOL = 'iSCSI/FC' # Nothing is actually done with this field
INFINIHOST_VERSION_FILE = "/opt/infinidat/host-power-tools/src/infi/vendata/powertools/__version__.py"


class InfiniboxException(exception.CinderException):
    pass


class ISCSIGWTimeoutException(exception.CinderException):
    pass


class ISCSIGWVolumeNotExposedException(exception.CinderException):
    pass


class InfiniBoxVolumeDriverConnectionException(exception.CinderException):
    pass


@contextmanager
def _infinisdk_to_cinder_exceptions_context():
    from infinisdk.core.exceptions import InfiniSDKException
    try:
        yield
    except InfiniSDKException, e:
        LOG.exception("Caught InfiniSDK")
        raise InfiniSDKException(str(e))


def _log_decorator(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        LOG.info("--> {0}({1})".format(func.__name__, '...'))
        return_value = func(self, *args, **kwargs)
        LOG.info("<-- {0!r}".format(return_value))
        return return_value
    return wrapper


def _infinisdk_to_cinder_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with _infinisdk_to_cinder_exceptions_context():
            return f(*args, **kwargs)
    return _log_decorator(wrapper)


def get_os_hostname():
    from socket import getfqdn
    return getfqdn()


def get_os_platform():
    from platform import platform
    return platform()


def get_powertools_version():
    """[root@io102 ~]# cat /opt/infinidat/host-power-tools/src/infi/vendata/powertools/__version__.py
    __version__ = "1.7.post12.g0e465ca"
    __git_commiter_name__ = "Arnon Yaari"
    __git_commiter_email__ = "arnony@infinidat.com"
    __git_branch__ = '(detached from 0e465ca)'
    __git_remote_tracking_branch__ = '(No remote tracking)'
    __git_remote_url__ = '(Not remote tracking)'
    __git_head_hash__ = '0e465ca976456a5bb7af814d075958990d07a7cc'
    __git_head_subject__ = 'TRIVIAL update test name'
    __git_head_message__ = ''
    __git_dirty_diff__ = ''"""
    try:
        with open(INFINIHOST_VERSION_FILE) as fd:
            return fd.read().splitlines()[0].split('=').strip().strip('"')
    except:
        return '0'


class InfiniboxVolumeDriver(driver.VolumeDriver):
    VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self.configuration.append_config_values(san_opts)
        self.system = None
        self.pool = None
        self.volume_stats = None

    @_infinisdk_to_cinder_exceptions
    def do_setup(self, context):
        from infinisdk.core.exceptions import ObjectNotFound
        from infinidat_openstack.config import is_masked, unmask
        for key in ('infinidat_provision_type', 'infinidat_pool_id', 'san_login', 'san_password'):
            if not self.configuration.safe_get(key):
                raise exception.InvalidInput(reason=translate("{0} must be set".format(key)))

        provision_type = self.configuration.infinidat_provision_type
        if provision_type.upper() not in ('THICK', 'THIN'):
            raise exception.InvalidInput(reason=translate("infinidat_provision_type must be THICK or THIN"))

        from infinisdk import InfiniBox
        self.system = InfiniBox(self.configuration.san_ip,
                             auth=(self.configuration.san_login,
                                   unmask(self.configuration.san_password) if \
                                   is_masked(self.configuration.san_password) else self.configuration.san_password))

        try:
            self._get_pool()  # we want to search for the pool here so we fail if we can't find it.
        except ObjectNotFound:
            if not self.configuration.infinidat_allow_pool_not_found:
                raise
            LOG.info("InfiniBox pool not found, but infinidat_allow_pool_not_found is set")

    # Since we no longer inherit from SanDriver, we have to implement the four following methods:

    @_infinisdk_to_cinder_exceptions
    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    @_infinisdk_to_cinder_exceptions
    def create_export(self, context, volume):
        """Exports the volume."""
        pass

    @_infinisdk_to_cinder_exceptions
    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    @_infinisdk_to_cinder_exceptions
    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        if not self.configuration.san_password:
            raise exception.InvalidInput(reason=_('Specify san_password'))

        # The san_ip must always be set, because we use it for the target
        if not self.configuration.san_ip:
            raise exception.InvalidInput(reason=_("san_ip must be set"))

    @_infinisdk_to_cinder_exceptions
    def create_volume(self, cinder_volume):
        infinidat_volume = self.system.volumes.create(name=self._create_volume_name(cinder_volume),
                                                      size=cinder_volume.size * GiB,
                                                      pool=self._get_pool(),
                                                      provisioning=self._get_provisioning())
        self._set_volume_or_snapshot_metadata(infinidat_volume, cinder_volume)

    @_infinisdk_to_cinder_exceptions
    def delete_volume(self, cinder_volume):
        from infinisdk.core.exceptions import ObjectNotFound
        try:
            infinidat_volume = self._find_volume(cinder_volume)
        except ObjectNotFound:
            LOG.info("delete_volume: volume {0!r} not found in InfiniBox, returning None".format(cinder_volume))
            return
        metadata = infinidat_volume.get_metadata()
        delete_method_name = "purge" if self.configuration.infinidat_purge_volume_on_deletion else "delete"
        if metadata.get("delete_parent", "false").lower() == "true":  # support cloned volumes
            getattr(infinidat_volume.get_parent(), delete_method_name)()
        else:
            getattr(infinidat_volume, delete_method_name)()

    def _wait_for_iscsi_host(self, initiator):
        start = time()
        while time() - start < self.configuration.infinidat_iscsi_gw_timeout_sec:

            for host in self.system.get_hosts():
                if initiator == host.get_metadata().get('iscsi_manager_iqn'):
                    return host

            sleep(self.configuration.infinidat_iscsi_gw_time_between_retries_sec)

        raise ISCSIGWTimeoutException("_wait_for_iscsi_host: no host with inq {0!r} in its metadata exists on box".format(initiator))

    def _find_target_by_metadata_change(self, old_metadata, new_metadata):
        for key in new_metadata:
            if not key.endswith('_change_counter'):
                continue
            if int(old_metadata.get(key, 0)) < int(new_metadata[key]):
                host_id = key.lstrip('iscsi_host_').rstrip('_change_counter')
                return self.system.hosts.get(id=int(host_id))
        return None

    def _wait_for_any_target_to_update_lun_mappings_on_host(self, host, old_metadata):
        start = time()
        while time() - start < self.configuration.infinidat_iscsi_gw_timeout_sec:

            target_iscsi_gateway = self._find_target_by_metadata_change(old_metadata, host.get_metadata())
            if target_iscsi_gateway:
                return target_iscsi_gateway

            sleep(self.configuration.infinidat_iscsi_gw_time_between_retries_sec)

        message = "_wait_for_any_target_to_update_lun_mappings_on_host: no iscsi-gateway found that performed a change against the iSCSI client host (name={0!r}, id={1}, metadata={2})"
        message = message.format(host.get_name(), host.get_id(), old_metadata)
        raise ISCSIGWVolumeNotExposedException(message)

    @_infinisdk_to_cinder_exceptions
    def initialize_connection(self, cinder_volume, connector):
        # connector is a dict containing information about the connection. For example:
        # connector={u'ip': u'172.16.86.169', u'host': u'openstack01', u'wwnns': [u'20000000c99115ea'],
        #            u'initiator': u'iqn.1993-08.org.debian:01:1cef2344a325', u'wwpns': [u'10000000c99115ea']}

        self._assert_connector(connector)
        methods = dict(fc=self._initialize_connection__fc,
                       iscsi=self._initialize_connection__iscsi)
        return self._handle_connection(methods, cinder_volume, connector)

    def _initialize_connection__fc(self, cinder_volume, connector):
        infinidat_volume = self._find_volume(cinder_volume)
        for wwpn in connector[u'wwpns']:
            host = self._find_or_create_host_by_wwpn(wwpn)
            self._set_host_metadata(host)
            lun = host.map_volume(infinidat_volume)
            access_mode = 'ro' if infinidat_volume.get_write_protected() else 'rw'
            target_wwn = [str(wwn) for wwn in self.system.get_fiber_target_addresses()]

        # See comments in cinder/volume/driver.py:FibreChannelDriver about the structure we need to return.
        return dict(driver_volume_type='fibre_channel',
                    data=dict(target_discovered=False, target_wwn=target_wwn, target_lun=lun, access_mode=access_mode))

    def _initialize_connection__iscsi(self, cinder_volume, connector):
        infinidat_volume = self._find_volume(cinder_volume)
        host = self._wait_for_iscsi_host(connector[u'initiator']) # raises error after timeout
        self._set_host_metadata(host)

        # we would like to compare before/after the map to make sure at least one target is aware of the map
        metadata_before_map = host.get_metadata()

        lun = host.map_volume(infinidat_volume)
        LOG.info("Volume(name={0!r}, id={1}) mapped to Host (name={2!r}, id={3}) successfully".format(
                    infinidat_volume.get_name(), infinidat_volume.get_id(), host.get_name(), host.get_id()))

        # We wait for the volume to be exposed via the gateway
        target_host = self._wait_for_any_target_to_update_lun_mappings_on_host(host, metadata_before_map)

        iscsi_target_metadata = target_host.get_metadata()
        target_iqn = iscsi_target_metadata.get('iscsi_manager_iqn')
        target_portal = iscsi_target_metadata.get('iscsi_manager_portal')
        access_mode = 'ro' if infinidat_volume.get_write_protected() else 'rw'

        # the interface states we need to return iSCSI target info but we have several
        # so we just return one that we know that mapped the volume to the client
        return dict(driver_volume_type='iscsi',
                    data=dict(
                              target_discovered=True,
                              volume_id=cinder_volume.id,
                              access_mode=access_mode,
                              target_portal=target_portal,
                              target_iqn=target_iqn,
                              target_lun=lun,
                              ))

    def _handle_connection(self, protocol_methods, cinder_volume, connector, *args, **kwargs):
        preferred_fc = self.configuration.infinidat_prefer_fc
        fc, iscsi = connector.get('wwpns'), connector.get('initiator')
        if not fc and not iscsi:
            raise exception.Invalid(translate(("no wwpns or iscsi initiator in connector {0}".format(connector))))
        elif fc and (not iscsi or preferred_fc):
            return protocol_methods['fc'](cinder_volume, connector, *args, **kwargs)
        else:
            return protocol_methods['iscsi'](cinder_volume, connector, *args, **kwargs)

    @_infinisdk_to_cinder_exceptions
    def terminate_connection(self, cinder_volume, connector, force=False):
        self._assert_connector(connector)
        methods = dict(fc=self._terminate_connection__fc,
                       iscsi=self._terminate_connection__iscsi)
        return self._handle_connection(methods, cinder_volume, connector, force=force)

    def _terminate_connection__fc(self, cinder_volume, connector, force=False):
        from infinisdk.core.exceptions import ObjectNotFound
        infinidat_volume = self._find_volume(cinder_volume)
        for wwpn in connector[u'wwpns']:
            try:
                host = self._find_host_by_wwpn(wwpn)
            except ObjectNotFound:
                continue
            self._set_host_metadata(host)
            host.unmap_volume(infinidat_volume, force=force)
            self._delete_host_if_unused(host)

    def _terminate_connection__iscsi(self, cinder_volume, connector, force=False):
        infinidat_volume = self._find_volume(cinder_volume)
        try:
            host = self._wait_for_iscsi_host(connector['initiator']) # raises error after timeout
        except ISCSIGWTimeoutException:
            return
        self._set_host_metadata(host)
        metadata_before_unmap = host.get_metadata()
        host.unmap_volume(infinidat_volume, force=force)
        LOG.info("Volume(name={0!r}, id={1}) unmapped from Host (name={2!r}, id={3}) successfully".format(
                    infinidat_volume.get_name(), infinidat_volume.get_id(), host.get_name(), host.get_id()))

        # We wait for the volume to be unexposed via the gateway
        self._wait_for_any_target_to_update_lun_mappings_on_host(host, metadata_before_unmap)

    @_infinisdk_to_cinder_exceptions
    def create_volume_from_snapshot(self, cinder_volume, cinder_snapshot):
        infinidat_snapshot = self._find_snapshot(cinder_snapshot)
        if cinder_volume.size * GiB != infinidat_snapshot.get_size():
            raise exception.InvalidInput(reason=translate("cannot create a volume with size different than its snapshot"))
        infinidat_volume = infinidat_snapshot.create_clone(name=self._create_volume_name(cinder_volume))
        self._set_volume_or_snapshot_metadata(infinidat_volume, cinder_volume)

    @_infinisdk_to_cinder_exceptions
    def create_cloned_volume(self, tgt_cinder_volume, src_cinder_volume):
        if tgt_cinder_volume.size != src_cinder_volume.size:
            raise exception.InvalidInput(reason=translate("cannot create a cloned volume with size different from source"))
        src_infinidat_volume = self._find_volume(src_cinder_volume)
        # We first create a snapshot and then a clone from that snapshot.
        snapshot = src_infinidat_volume.create_snapshot(name=self._create_snapshot_name(src_cinder_volume) + "-internal")
        self._set_obj_metadata(snapshot, {
            "cinder_id": "",
            "internal": "true"
            })
        # We now create a clone from the snapshot
        tgt_infinidat_volume = snapshot.create_clone(name=self._create_volume_name(tgt_cinder_volume))
        self._set_volume_or_snapshot_metadata(tgt_infinidat_volume, tgt_cinder_volume, delete_parent=True)

    @_infinisdk_to_cinder_exceptions
    def extend_volume(self, cinder_volume, new_size):
        LOG.info("InfiniboxVolumeDriver.extend_volume")
        infinidat_volume = self._find_volume(cinder_volume)
        new_size_in_bytes = new_size * GiB
        if infinidat_volume.get_size() != new_size_in_bytes:
            if infinidat_volume.get_size() > new_size_in_bytes:
                raise exception.InvalidInput(reason=translate("cannot resize volume: new size must be greater or equal to current size"))
            infinidat_volume.set_size(new_size_in_bytes)

    @_infinisdk_to_cinder_exceptions
    def migrate_volume(self, context, volume, host):
        return False, None  # not supported: we can't migrate a volume between pools or between Infinibox machines

    @_infinisdk_to_cinder_exceptions
    def create_snapshot(self, cinder_snapshot):
        infinidat_volume = self._find_volume(cinder_snapshot.volume)
        infinidat_snapshot = infinidat_volume.create_snapshot(name=translate(self._create_snapshot_name(cinder_snapshot)))
        self._set_volume_or_snapshot_metadata(infinidat_snapshot, cinder_snapshot)

    @_infinisdk_to_cinder_exceptions
    def delete_snapshot(self, cinder_snapshot):
        infinidat_snapshot = self._find_snapshot(cinder_snapshot)
        infinidat_snapshot.delete()

    @_infinisdk_to_cinder_exceptions
    def get_volume_stats(self, refresh=False):
        if refresh or not self.volume_stats:
            self._update_volume_stats()
        return self.volume_stats

    def _update_volume_stats(self):
        from infinisdk.core.exceptions import ObjectNotFound
        """Retrieve stats info from volume group."""

        data = {}
        system_and_pool_name = "infinibox-{0}-pool-{1}".format(self.system.get_serial(), self.configuration.infinidat_pool_id)
        data["volume_backend_name"] = system_and_pool_name
        data["vendor_name"] = STATS_VENDOR
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = STATS_PROTOCOL

        try:
            data['total_capacity_gb'] = self._get_pool().get_physical_capacity() / GiB
            data['free_capacity_gb'] = self._get_pool().get_free_physical_capacity() / GiB
        except ObjectNotFound:
            data['total_capaceity_gb'] = 0
            data['free_capacity_gb'] = 0

        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self.volume_stats = data

    def _get_pool(self):
        if not self.pool:
            pools = self.system.pools.find(id=int(self.configuration.infinidat_pool_id))
            if not pools:
                raise exception.InvalidInput(translate("pool {0} not found".format(int(self.configuration.infinidat_pool_id))))
            self.pool = pools[0]
        return self.pool

    def _find_volume(self, cinder_volume):
        return self.system.volumes.get(name=self._create_volume_name(cinder_volume))

    def _find_snapshot(self, cinder_snapshot):
        return self.system.volumes.get(name=self._create_snapshot_name(cinder_snapshot))

    def _find_host_by_wwpn(self, wwpn):
        return self.system.hosts.get(name=self._create_host_name_by_wwpn(wwpn))

    def _find_or_create_host_by_wwpn(self, wwpn):
        name = self._create_host_name_by_wwpn(wwpn)
        host = self.system.hosts.safe_get(name=name)
        if not host:
            host = self.system.hosts.create(name=name)
            host.add_fc_port(wwpn)
        return host

    def _delete_host_if_unused(self, host):
        from infinisdk.core.exceptions import APICommandFailed
        try:
            host.delete()
        except APICommandFailed, e:
            if 'HOST_NOT_EMPTY' in e.response.response.content:
                pass  # host still contains mappings
            else:
                raise  # some other bad thing happened

    def _get_provisioning(self):
        return self.configuration.infinidat_provision_type.upper()

    def _create_volume_name(self, cinder_volume):
        return "{0}-{1}".format(self.configuration.infinidat_volume_name_prefix, cinder_volume.id)

    def _create_snapshot_name(self, cinder_snapshot):
        return "{0}-{1}".format(self.configuration.infinidat_snapshot_name_prefix, cinder_snapshot.id)

    def _create_host_name_by_wwpn(self, wwpn):
        return "{0}-{1}".format(self.configuration.infinidat_host_name_prefix, wwpn)

    def _set_volume_or_snapshot_metadata(self, infinidat_volume, cinder_volume, delete_parent=False):
        metadata = {
            "cinder_id": str(cinder_volume.id),
            "delete_parent": str(delete_parent),
            "cinder_display_name": str(cinder_volume.display_name)
            }
        self._set_obj_metadata(infinidat_volume, metadata)

    def _set_host_metadata(self, infinidat_host):
        metadata = {
            "hostname": get_os_hostname(),
            "platform": get_os_platform(),
            "powertools_version": get_powertools_version()
            }
        self._set_obj_metadata(infinidat_host, metadata)

    def _set_obj_metadata(self, obj, metadata):
        metadata["system"] = str(SYSTEM_METADATA_VALUE)
        metadata["driver_version"] = str(self.VERSION)
        obj.set_metadata(**metadata)

    def _assert_connector(self, connector):
        if ((not u'wwpns' in connector or not connector[u'wwpns']) and
            (not u'initiator' in connector or not connector[u'initiator']) ):
            LOG.warn("no WWPN or iSCSI initiator was provided in connector: {0!r}".format(connector))
            raise exception.Invalid(translate('No WWPN or iSCSI initiator was received'))

    def _flush_caches_for_specific_device(self, attach_info):
        import os
        from fcntl import ioctl
        LOG.info("attempting to flush caches for {0!r}".format(attach_info))
        fd = os.open(attach_info['device']['path'], os.O_RDONLY)
        try:
            ioctl(fd, 4705) # BLKFLSBUF
        finally:
            os.close(fd)
        self._sleep_after_sync()

    def _call_sync(self):
        from ctypes import CDLL
        libc = CDLL("libc.so.6")
        libc.sync()
        libc.sync()
        libc.sync()
        self._sleep_after_sync()

    def _sleep_after_sync(self):
        # the call returns before the cache is actually flushed to disk, so we wait a bit
        sleep(self.configuration.infinidat_sync_sleep_duration)

    def _flush_caches_to_disk(self, *args, **kwargs):
        # http://blogs.gnome.org/cneumair/2006/02/11/ioctl-fsync-how-to-flush-block-device-buffers
        # http://stackoverflow.com/questions/9551838/how-to-purge-disk-i-o-caches-on-linux
        try:
            # commit b868ae707f9ecbe254101e21d9d7ffa0b05b17d1 changed the intergace for _detach_volume
            # we need the attach_info instance, so we use this hack
            from .getcallargs import getcallargs # new in Python-2.7, we bundled the function for Python-2.6
            attach_info = getcallargs(super(InfiniboxVolumeDriver, self)._detach_volume, *args, **kwargs)['attach_info']
            self._flush_caches_for_specific_device(attach_info)
        except:
            # this can fail,
            # for example, when cinder-volume runs under user 'cinder' which does not have permissions to read /dev/sdX
            # so in case this fails, we just call sync
            LOG.debug("failed to flush cache for specific device, will just call sync instead")
            try:
                self._call_sync()
            except:
                LOG.exception("call to sync failed, caches are not flushed")

    def _detach_volume(self, *args, **kwargs):
        # before detaching volumes, we want to call sync to make sure all the IOs are written to disk
        self._flush_caches_to_disk(*args, **kwargs)
        super(InfiniboxVolumeDriver, self)._detach_volume(*args, **kwargs)
