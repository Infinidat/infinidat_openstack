import test_case
import time
from unittest import SkipTest
from infi.unittest import parameters
from infi.pyutils.contexts import contextmanager
from infi.pyutils.retry import retry_func, WaitAndRetryStrategy
from tests.test_common import get_admin_password
from cinderclient.v2.consistencygroups import ConsistencygroupManager

def get_cinder_v2_client(host="localhost"):
    from cinderclient.v2 import client
    return client.Client("admin", get_admin_password(), "admin", "http://{}:5000/v2.0/".format(host))


class CGRealTestCaseMixin(test_case.RealTestCaseMixin):

    @classmethod
    def skip_if_needed(cls):
        from cinderclient.exceptions import NotFound, ClientException
        try:
            cgm = ConsistencygroupManager(get_cinder_v2_client())
            cgm.list()
        except (ImportError, NotFound, ClientException):
            raise SkipTest("This openstack version doesn't support consistency groups")

    @classmethod
    def setup_host(cls):
        cls.skip_if_needed()
        super(CGRealTestCaseMixin, cls).setup_host()

    @classmethod
    def setup_infinibox(cls):
        cls.skip_if_needed()
        cls.system = cls.system_factory.allocate_infinidat_system(
            expiration_in_seconds=3600*2,
            labels=['ci-ready','infinibox-2.2'])
        cls.system.purge()
        cls.infinisdk = cls.system.get_infinisdk()

    @classmethod
    def cleanup_infiniboxes_from_cinder(cls):
        cls.skip_if_needed()
        def cleanup_cgsnaps():
            from cinderclient.v2.cgsnapshots import CgsnapshotManager
            cgsm = CgsnapshotManager(get_cinder_v2_client())
            for snap in cgsm.list():
                snap.delete()

        def remove_volumes_from_cgs():
            cinder_client = get_cinder_v2_client()
            cgm = ConsistencygroupManager(get_cinder_v2_client())
            for volume in cinder_client.volumes.list():
                if volume.consistencygroup_id:
                    cg = cgm.get(volume.consistencygroup_id)
                    cg.update(remove_volumes=volume.id)
                    cls.wait_for_removal_from_consistencygroup(volume, timeout=30)

        def cleanup_cgs():
            cgm = ConsistencygroupManager(get_cinder_v2_client())
            for cg in cgm.list():
                cg.delete()
        cleanup_cgsnaps()
        remove_volumes_from_cgs()
        cleanup_cgs()
        super(CGRealTestCaseMixin, cls).cleanup_infiniboxes_from_cinder()


class CGTestsMixin(object):
    @contextmanager
    def volume_context(self, name, pool, consistencygroup_id=None, delete=True):
        from cinderclient.v2.volumes import VolumeManager
        vm = VolumeManager(get_cinder_v2_client())
        cgm = ConsistencygroupManager(get_cinder_v2_client())
        kwargs = {"name": name, "size": 1, "volume_type": self.get_infinidat_volume_type(pool)}
        if consistencygroup_id:
            kwargs["consistencygroup_id"] = consistencygroup_id
        vol = vm.create(**kwargs)
        self.wait_for_object_creation(vol, timeout=30)
        try:
            yield vol
        finally:
            if delete:
                vol.get()
                if vol.consistencygroup_id:
                    cg = cgm.get(vol.consistencygroup_id)
                    cg.update(remove_volumes=vol.id)
                    self.wait_for_removal_from_consistencygroup(vol, timeout=30)
                vol.delete()
                self.wait_for_object_deletion(vol, timeout=30)

    @contextmanager
    def cg_context(self, name, pool):
        cgm = ConsistencygroupManager(get_cinder_v2_client())
        cg = cgm.create(name=name, volume_types=self.get_infinidat_volume_type(pool))
        self.wait_for_object_creation(cg, timeout=30)
        try:
            yield cg
        finally:
            cg.delete()
            self.wait_for_object_deletion(cg, timeout=30)

    @contextmanager
    def cgsnapshot_context(self, cg, name):
        from cinderclient.v2.cgsnapshots import CgsnapshotManager
        cgsm = CgsnapshotManager(get_cinder_v2_client())
        cgs = cgsm.create(consistencygroup_id=cg.id, name=name)
        self.wait_for_object_creation(cgs, timeout=30)
        try:
            yield cgs
        finally:
            cgs.delete()
            self.wait_for_object_deletion(cgs, timeout=30)

    def test_sanity(self):
        from cinderclient.v2.volume_snapshots import SnapshotManager

        sm = SnapshotManager(get_cinder_v2_client())
        with self.provisioning_pool_context() as pool:
            with self.cg_context(name="cg1", pool=pool) as cg:
                with self.volume_context(name="vol1", pool=pool, consistencygroup_id=cg.id) as vol:
                    with self.cgsnapshot_context(cg, "cg1snap1") as cgsnap:
                        from cinderclient.v2.volume_snapshots import SnapshotManager
                        sm = SnapshotManager(get_cinder_v2_client())
                        snaps = list(sm.list())
                        self.assertTrue(any([s.volume_id == vol.id for s in snaps]))
                        infinidat_cg = self.infinisdk.cons_groups.get_all()[0]
                        self.assertEquals(infinidat_cg.get_metadata_value('cinder_id'), cg.id)
                        infinidat_vol = infinidat_cg.get_members()[0]
                        self.assertEquals(infinidat_vol.get_metadata_value('cinder_id'), vol.id)

    def test_add_volume(self):
        from cinderclient.v2.volume_snapshots import SnapshotManager

        sm = SnapshotManager(get_cinder_v2_client())
        with self.provisioning_pool_context() as pool:
            with self.cg_context(name="cg1", pool=pool) as cg:
                with self.volume_context(name="vol1", pool=pool) as vol1:
                    cg.update(add_volumes=vol1.id)
                    time.sleep(5) # Just to make sure the volume was added (we don't have "wait_for_object_addition")
                    with self.cgsnapshot_context(cg, "cg1snap1") as cgsnap:
                        from cinderclient.v2.volume_snapshots import SnapshotManager
                        sm = SnapshotManager(get_cinder_v2_client())
                        snaps = list(sm.list())
                        self.assertTrue(any([s.volume_id == vol1.id for s in snaps]))
                        infinidat_cg = self.infinisdk.cons_groups.get_all()[0]
                        self.assertEquals(infinidat_cg.get_metadata_value('cinder_id'), cg.id)
                        infinidat_vol = infinidat_cg.get_members()[0]
                        self.assertEquals(infinidat_vol.get_metadata_value('cinder_id'), vol1.id)
                        with self.volume_context(name="vol2", pool=pool, consistencygroup_id=cg.id) as vol2:
                            with self.cgsnapshot_context(cg, "cg1snap2") as cgsnap2:
                                snaps = list(sm.list())
                                self.assertEquals(sorted([s.volume_id for s in snaps]), sorted([vol1.id, vol1.id, vol2.id]))


class CGTests_Fibre_Real(test_case.OpenStackFibreChannelTestCase, CGRealTestCaseMixin, CGTestsMixin):
    pass
