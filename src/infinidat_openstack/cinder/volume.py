from cinder.openstack.common import log as logging
from cinder.volume.drivers.san import san
from cinder import exception

from contextlib import contextmanager
from capacity import GiB
from infi.pyutils.decorators import wraps

LOG = logging.getLogger(__name__)

# FIXME configuration
# Add provisioning: thick or thin
# Add pool
# Do we want to have default format for the volume/snapshot names so the admin will see them as openstack volumes?
# TODO add metadata on object that says it's managed by openstack and maybe the specific backend that handles it?
SYSTEM_METADATA_VALUE = 'openstack'
STATS_VENDOR = 'Infinidat'
STATS_PROTOCOL = 'FibreChannel'


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


def _infinipy_to_cinder_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with _infinipy_to_cinder_exceptions_context():
            return f(*args, **kwargs)
    return wrapper


class InfiniboxVolumeDriver(san.SanDriver):
    VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)

        self.system = None
        self.pool = None
        self.volume_stats = None

    @_infinipy_to_cinder_exceptions
    def do_setup(self, context):
        from infinipy import System
        self.system = System(self.configuration.san_ip,
                             username=self.configuration.san_login,
                             password=self.configuration.san_password)
        # FIXME if pool is configured, fetch the pool object.

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
            host.unmap_volume(infinidat_volume, force=force)
            self._delete_host_if_unused(host)

    @_infinipy_to_cinder_exceptions
    def create_volume_from_snapshot(self, cinder_volume, cinder_snapshot):
        infinidat_snapshot = self._find_snapshot(cinder_snapshot)
        if cinder_volume.size * GiB != infinidat_snapshot.get_size():
            raise InfiniboxException("cannot create a volume with size different than its snapshot")
        infinidat_volume = infinidat_snapshot.create_clone(name=self._create_volume_name(cinder_volume))
        self._set_volume_or_snapshot_metadata(infinidat_volume, cinder_volume)

    @_infinipy_to_cinder_exceptions
    def create_cloned_volume(self, tgt_cinder_volume, src_cinder_volume):
        if tgt_cinder_volume.size != src_cinder_volume:
            raise InfiniboxException("cannot create a cloned volume with size different from source")
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
                raise InfiniboxException("cannot resize volume: only master volumes can be resized")
            if infinidat_volume.get_size() < new_size_in_bytes:
                raise InfiniboxException("cannot resize volume: new size must be greater or equal to current size")
            infinidat_volume.set_size(new_size_in_bytes)

    @_infinipy_to_cinder_exceptions
    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host."""
        LOG.info("InfiniboxVolumeDriver.migrate_volume")
        raise NotImplementedError()

    @_infinipy_to_cinder_exceptions
    def create_snapshot(self, cinder_snapshot):
        infinidat_volume = self._find_volume(cinder_snapshot.volume)
        infinidat_snapshot = infinidat_volume.create_snapshot(name=self._create_snapshot_name(cinder_snapshot))
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
        backend_name = self.configuration.safe_get('volume_backend_name')
        #system_and_pool_name = "{0}-{1}".format(self.system.get_name(), self._get_pool().get_name())
        data["volume_backend_name"] = backend_name or "system_and_pool_name"
        data["vendor_name"] = STATS_VENDOR
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = STATS_PROTOCOL

        data['total_capacity_gb'] = self._get_pool().get_thick_size() / GiB
        data['free_capacity_gb'] = self._get_pool().get_free_thick_size() / GiB
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self.volume_stats = data

    def _get_pool(self):
        if not self.pool:
            # Pool not configured by default, we'll get the first pool we find.
            # Note that we don't save this pool in our class because if it gets deleted we'll always fail to create
            # volumes and that's not the desired behavior for a user who didn't configure a specific pool.
            pools = self.system.objects.Pool.find()
            if not pools:
                # FIXME raise better exception
                raise InfiniboxException("no pool is defined in the system")
            return pools[0]
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
        # FIXME get from configuration
        return 'THICK'

    def _create_volume_name(self, cinder_volume):
        # FIXME get from configuration
        return "openstack-vol-{0}".format(cinder_volume.id)

    def _create_snapshot_name(self, cinder_snapshot):
        return "openstack-snap-{0}".format(cinder_snapshot.id)

    def _create_host_name_by_wwpn(self, wwpn):
        return "openstack-host-{0}".format(wwpn)

    def _set_volume_or_snapshot_metadata(self, infinidat_volume, cinder_volume, delete_parent=False):
        infinidat_volume.set_metadata("cinder_id", cinder_volume.id)
        infinidat_volume.set_metadata("delete_parent", delete_parent)
        self._set_basic_metadata(infinidat_volume)

    def _set_basic_metadata(self, infinidat_volume):
        infinidat_volume.set_metadata("system", SYSTEM_METADATA_VALUE)
        infinidat_volume.set_metadata("driver_version", self.VERSION)

    def _assert_connector_has_wwpns(self, connector):
        if not u'wwpns' in connector or not connector[u'wwpns']:
            LOG.warn("no WWPN was provided in connector: {0!r}".format(connector))
            raise InfiniboxException(u'can map a volume only to WWPN, but no WWPN was received')
