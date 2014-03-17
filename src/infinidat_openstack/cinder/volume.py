from oslo.config import cfg
try:
    from cinder.openstack.common import log as logging
    from cinder.openstack.common.gettextutils import _ as translate
    from cinder.volume.drivers.san import san
    from cinder import exception
except (ImportError, NameError):  # importing with just python hits NameErorr from the san module, the _ trick
    from .mock import logging, translate
    from . import mock as san
    from . import mock as exception

from contextlib import contextmanager
from functools import wraps
from capacity import GiB
from infi.pyutils.decorators import wraps

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('infinidat_pool_id', help='id the pool from which volumes are allocated', default=None),
    cfg.StrOpt('infinidat_provision_type', help='Provisioning type (thick or thin)', default='thick'),
    cfg.StrOpt('infinidat_volume_name_prefix', help='Cinder volume name prefix in Infinibox', default='openstack-vol'),
    cfg.StrOpt('infinidat_snapshot_name_prefix', help='Cinder snapshot name prefix in Infinibox',
               default='openstack-snap'),
    cfg.StrOpt('infinidat_host_name_prefix', help='Cinder host name prefix in Infinibox', default='openstack-host'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


SYSTEM_METADATA_VALUE = 'openstack'
STATS_VENDOR = 'Infinidat'
STATS_PROTOCOL = 'FibreChannel'
INFINIHOST_VERSION_FILE = "/opt/infinidat/host-power-tools/src/infi/vendata/powertools/__version__.py"


class InfiniboxException(exception.CinderException):
    pass


@contextmanager
def _infinipy_to_cinder_exceptions_context():
    from infinipy.exceptions import InfinipyException
    try:
        yield
    except InfinipyException, e:
        LOG.exception("Caught Infinibox API exception")
        raise InfiniboxException(str(e))


def _log_decorator(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        LOG.info("--> {0}({1})".format(func.__name__, '...'))
        return_value = func(self, *args, **kwargs)
        LOG.info("<-- {0!r}".format(return_value))
        return return_value
    return wrapper


def _infinipy_to_cinder_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with _infinipy_to_cinder_exceptions_context():
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


class InfiniboxVolumeDriver(san.SanDriver):
    VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self.system = None
        self.pool = None
        self.volume_stats = None

    @_infinipy_to_cinder_exceptions
    def do_setup(self, context):
        for key in ('infinidat_provision_type', 'infinidat_pool_id', 'san_login', 'san_password'):
            if not self.configuration.safe_get(key):
                raise exception.InvalidInput(reason=translate("{0} must be set".format(key)))

        provision_type = self.configuration.infinidat_provision_type
        if provision_type.upper() not in ('THICK', 'THIN'):
            raise exception.InvalidInput(reason=translate("infinidat_provision_type must be THICK or THIN"))

        from infinipy import System
        self.system = System(self.configuration.san_ip,
                             username=self.configuration.san_login,
                             password=self.configuration.san_password)
        self._get_pool()  # we want to search for the pool here so we fail if we can't find it.

    @_infinipy_to_cinder_exceptions
    def create_volume(self, cinder_volume):
        infinidat_volume = self.system.objects.Volume.create(name=self._create_volume_name(cinder_volume),
                                                             size=cinder_volume.size * GiB,
                                                             pool=self._get_pool(),
                                                             provisioning=self._get_provisioning())
        self._set_volume_or_snapshot_metadata(infinidat_volume, cinder_volume)

    @_infinipy_to_cinder_exceptions
    def delete_volume(self, cinder_volume):
        infinidat_volume = self._find_volume(cinder_volume)
        metadata = infinidat_volume.get_metadata()
        if metadata.get("delete_parent", "false").lower() == "true":  # support cloned volumes
            infinidat_volume.get_parent().delete()
        else:
            infinidat_volume.delete()

    @_infinipy_to_cinder_exceptions
    def initialize_connection(self, cinder_volume, connector):
        # connector is a dict containing information about the connection. For example:
        # connector={u'ip': u'172.16.86.169', u'host': u'openstack01', u'wwnns': [u'20000000c99115ea'],
        #            u'initiator': u'iqn.1993-08.org.debian:01:1cef2344a325', u'wwpns': [u'10000000c99115ea']}
        self._assert_connector_has_wwpns(connector)

        infinidat_volume = self._find_volume(cinder_volume)
        for wwpn in connector[u'wwpns']:
            host = self._find_or_create_host_by_wwpn(wwpn)
            self._set_host_metadata(host)
            lun = host.map_volume(infinidat_volume)
            target_wwn = [str(wwn) for wwn in self.system.get_fiber_target_addresses()]
            access_mode = 'ro' if infinidat_volume.get_write_protected() else 'rw'
        # See comments in cinder/volume/driver.py:FibreChannelDriver about the structure we need to return.
        return dict(driver_volume_type='fibre_channel',
                    data=dict(target_discovered=False, target_wwn=target_wwn, target_lun=lun, access_mode=access_mode))

    @_infinipy_to_cinder_exceptions
    def terminate_connection(self, cinder_volume, connector, force=False):
        from infinipy.system.exceptions import NoObjectFound
        self._assert_connector_has_wwpns(connector)

        infinidat_volume = self._find_volume(cinder_volume)
        for wwpn in connector[u'wwpns']:
            try:
                host = self._find_host_by_wwpn(wwpn)
            except NoObjectFound:
                continue
            self._set_host_metadata(host)
            host.unmap_volume(infinidat_volume, force=force)
            self._delete_host_if_unused(host)

    @_infinipy_to_cinder_exceptions
    def create_volume_from_snapshot(self, cinder_volume, cinder_snapshot):
        infinidat_snapshot = self._find_snapshot(cinder_snapshot)
        if cinder_volume.size * GiB != infinidat_snapshot.get_size():
            raise exception.InvalidInput(reason=translate("cannot create a volume with size different than its snapshot"))
        infinidat_volume = infinidat_snapshot.create_clone(name=self._create_volume_name(cinder_volume))
        self._set_volume_or_snapshot_metadata(infinidat_volume, cinder_volume)

    @_infinipy_to_cinder_exceptions
    def create_cloned_volume(self, tgt_cinder_volume, src_cinder_volume):
        if tgt_cinder_volume.size != src_cinder_volume.size:
            raise exception.InvalidInput(reason=translate("cannot create a cloned volume with size different from source"))
        src_infinidat_volume = self._find_volume(src_cinder_volume)
        # We first create a snapshot and then a clone from that snapshot.
        snapshot = src_infinidat_volume.create_snapshot(name=self._create_snapshot_name(src_cinder_volume) + "-internal")
        self._set_basic_metadata(snapshot)
        snapshot.set_metadata("cinder_id", "")
        snapshot.set_metadata("internal", "true")
        # We now create a clone from the snapshot
        tgt_infinidat_volume = snapshot.create_clone(name=self._create_volume_name(tgt_cinder_volume))
        self._set_volume_or_snapshot_metadata(tgt_infinidat_volume, tgt_cinder_volume, delete_parent=True)

    @_infinipy_to_cinder_exceptions
    def extend_volume(self, cinder_volume, new_size):
        LOG.info("InfiniboxVolumeDriver.extend_volume")
        infinidat_volume = self._find_volume(cinder_volume)
        new_size_in_bytes = new_size * GiB
        if infinidat_volume.get_size() != new_size_in_bytes:
            if not infinidat_volume.is_master_volume():
                # Current limitation in Infinibox - cannot resize non-master volumes
                raise exception.InvalidInput(reason=translate("cannot resize volume: only master volumes can be resized"))
            if infinidat_volume.get_size() > new_size_in_bytes:
                raise exception.InvalidInput(reason=translate("cannot resize volume: new size must be greater or equal to current size"))
            infinidat_volume.set_size(new_size_in_bytes)

    @_infinipy_to_cinder_exceptions
    def migrate_volume(self, context, volume, host):
        return False, None  # not supported: we can't migrate a volume between pools or between Infinibox machines

    @_infinipy_to_cinder_exceptions
    def create_snapshot(self, cinder_snapshot):
        infinidat_volume = self._find_volume(cinder_snapshot.volume)
        infinidat_snapshot = infinidat_volume.create_snapshot(name=translate(self._create_snapshot_name(cinder_snapshot)))
        self._set_volume_or_snapshot_metadata(infinidat_snapshot, cinder_snapshot)

    @_infinipy_to_cinder_exceptions
    def delete_snapshot(self, cinder_snapshot):
        infinidat_snapshot = self._find_snapshot(cinder_snapshot)
        infinidat_snapshot.delete()

    @_infinipy_to_cinder_exceptions
    def get_volume_stats(self, refresh=False):
        if refresh or not self.volume_stats:
            self._update_volume_stats()
        return self.volume_stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        data = {}
        system_and_pool_name = "infinibox-{0}-pool-{1}".format(self.system.get_serial(), self._get_pool().get_id())
        data["volume_backend_name"] = system_and_pool_name
        data["vendor_name"] = STATS_VENDOR
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = STATS_PROTOCOL

        data['total_capacity_gb'] = self._get_pool().get_physical_capacity() / GiB
        data['free_capacity_gb'] = self._get_pool().get_free_physical_capacity() / GiB
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self.volume_stats = data

    def _get_pool(self):
        if not self.pool:
            pools = self.system.objects.Pool.find(id=int(self.configuration.infinidat_pool_id))
            if not pools:
                raise exception.InvalidInput(translate("pool {0} not found".format(int(self.configuration.infinidat_pool_id))))
            self.pool = pools[0]
        return self.pool

    def _find_volume(self, cinder_volume):
        return self.system.objects.Volume.get(name=self._create_volume_name(cinder_volume))

    def _find_snapshot(self, cinder_snapshot):
        return self.system.objects.Volume.get(name=self._create_snapshot_name(cinder_snapshot))

    def _find_host_by_wwpn(self, wwpn):
        return self.system.objects.Host.get(name=self._create_host_name_by_wwpn(wwpn))

    def _find_or_create_host_by_wwpn(self, wwpn):
        name = self._create_host_name_by_wwpn(wwpn)
        host = self.system.objects.Host.safe_get(name=name)
        if not host:
            host = self.system.objects.Host.create(name=name)
            host.add_fc_port(wwpn)
        return host

    def _delete_host_if_unused(self, host):
        from infinipy.system.exceptions import APICommandFailed
        try:
            host.delete()
        except APICommandFailed, e:
            if 'HOST_NOT_EMPTY' in e.ctx.raw_output:  # no need to really parse the JSON
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
        infinidat_volume.set_metadata("cinder_id", str(cinder_volume.id))
        infinidat_volume.set_metadata("delete_parent", str(delete_parent))
        infinidat_volume.set_metadata("cinder_display_name", str(cinder_volume.display_name))
        self._set_basic_metadata(infinidat_volume)

    def _set_host_metadata(self, infinidat_host):
        infinidat_host.set_metadata("hostname", get_os_hostname())
        infinidat_host.set_metadata("platform", get_os_platform())
        infinidat_host.set_metadata("powertools_version", get_powertools_version())
        self._set_basic_metadata(infinidat_host)

    def _set_basic_metadata(self, infinidat_volume):
        infinidat_volume.set_metadata("system", str(SYSTEM_METADATA_VALUE))
        infinidat_volume.set_metadata("driver_version", str(self.VERSION))

    def _assert_connector_has_wwpns(self, connector):
        if not u'wwpns' in connector or not connector[u'wwpns']:
            LOG.warn("no WWPN was provided in connector: {0!r}".format(connector))
            raise exception.Invalid(translate('can map a volume only to WWPN, but no WWPN was received'))
