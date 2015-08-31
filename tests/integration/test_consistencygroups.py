import test_case
from infi.unittest import parameters
from infi.pyutils.retry import retry_func, WaitAndRetryStrategy
from infi.pyutils.contexts import contextmanager


def get_cinder_v2_client(host="localhost"):
    from cinderclient.v2 import client
    return client.Client("admin", "admin", "admin", "http://{}:5000/v2.0/".format(host))


class CGRealTestCaseMixin(test_case.RealTestCaseMixin):
    @classmethod
    def setup_infinibox(cls):
        cls.system = cls.system_factory.allocate_infinidat_system(
            expiration_in_seconds=3600,
            labels=['ci-ready','infinibox-2.2'])
        cls.system.purge()
        cls.infinisdk = cls.system.get_infinisdk()

    @classmethod
    def cleanup_infiniboxes_from_cinder(cls):
        def cleanup_cgsnaps():
            from cinderclient.v2.cgsnapshots import CgsnapshotManager
            cgsm = CgsnapshotManager(get_cinder_v2_client())
            for snap in cgsm.list():
                snap.delete()

        def cleanup_cgs():
            from cinderclient.v2.consistencygroups import ConsistencygroupManager
            cgm = ConsistencygroupManager(get_cinder_v2_client())
            for cg in cgm.list():
                cg.delete()
        cleanup_cgsnaps()
        cleanup_cgs()
        super(CGRealTestCaseMixin, cls).cleanup_infiniboxes_from_cinder()


class CGTestsMixin(object):
    def get_infinidat_volume_type(self):
        from cinderclient.v2.volume_types import VolumeTypeManager
        vtm = VolumeTypeManager(get_cinder_v2_client())
        return vtm.list()[0].id

    @contextmanager
    def volume_context(self, name, consistencygroup_id=None):
        from cinderclient.v2.volumes import VolumeManager
        vm = VolumeManager(get_cinder_v2_client())
        kwargs = {"name": name, "size": 1, "volume_type": self.get_infinidat_volume_type()}
        if consistencygroup_id:
            kwargs["consistencygroup_id"] = consistencygroup_id
        vol = vm.create(**kwargs)
        try:
            yield vol
        finally:
            vol.delete()

    @contextmanager
    def cg_context(self, name):
        from cinderclient.v2.consistencygroups import ConsistencygroupManager
        cgm = ConsistencygroupManager(get_cinder_v2_client())
        cg = cgm.create(name=name, volume_types=self.get_infinidat_volume_type())
        try:
            yield cg
        finally:
            cg.delete()

    @contextmanager
    def cgsnapshot_context(self, cg, name):
        from cinderclient.v2.cgsnapshots import CgsnapshotManager
        cgsm = CgsnapshotManager(get_cinder_v2_client())
        cgs = cgsm.create(consistencygroup_id=cg.id, name=name)
        try:
            yield cgs
        finally:
            cgs.delete()

    def test_sanity(self):
        from cinderclient.v2.volume_snapshots import SnapshotManager

        sm = SnapshotManager(get_cinder_v2_client())
        with self.provisioning_pool_context() as pool:
            with self.cg_context(name="cg1") as cg:
                with self.volume_context(name="vol1", consistencygroup_id=cg.id) as vol:
                    with self.cgsnapshot_context(cg, "cg1snap1") as cgsnap:
                        from cinderclient.v2.volume_snapshots import SnapshotManager
                        sm = SnapshotManager(get_cinder_v2_client())
                        snaps = list(sm.list())
                        self.assertTrue(any([s.volume_id == vol.id for s in snaps]))
                        infinidat_cg = self.infinisdk.cons_groups.get_all()[0]
                        self.assertEquals(infinidat_cg.get_metadata_value('cinder_id'), cg.id)
                        infinidat_vol = infinidat_cg.get_members()[0]
                        self.assertEquals(infinidat_vol.get_metadata_value('cinder_id'), vol.id)
                        # TODO add more volumes, create another snapshot
                        # TODO remove a volume
                        # TODO make sure the cinder snapshots are associated with the relevant infindiat snapshots




class CGTests_Fibre_Real(test_case.OpenStackFibreChannelTestCase, CGRealTestCaseMixin, CGTestsMixin):
    pass
