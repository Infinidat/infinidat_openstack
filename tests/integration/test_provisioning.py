import test_case
from infi.unittest import parameters
from infi.pyutils.retry import retry_func, WaitAndRetryStrategy

def setup_module():
    test_case.prepare_host()

def teardown_module():
    pass


class ProvisioningTestsMixin(object):
    def test_volume_type_is_registered(self):
        with self.provisioning_pool_context() as pool:
            display_name = "[InfiniBox] {}/{}".format(self.infinipy.get_name(), pool.get_name())
            volume_backend_name = "infinibox-{}-pool-{}".format(self.infinipy.get_serial(), pool.get_id())
            [volume_type] = [item for item in self.get_cinder_client().volume_types.findall()
                             if item.get_keys()["volume_backend_name"] == volume_backend_name]
            self.assertEquals(volume_type.name, display_name)

    def test_create_volume_in_one_pool(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    self.assertEquals(cinder_volume.id, infinibox_volume.get_metadata("cinder_id"))

    @parameters.iterate("volume_count", [2, 5])
    def test_create_multiple_volumes_in_one_pool(self, volume_count):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                cinder_volumes = [self.create_volume(1, pool=pool) for volume in range(volume_count)]
                infinibox_volumes, _ = get_diff()
                self.assertEquals([item.id for item in cinder_volumes],
                                  [item.get_metadata("cinder_id") for item in infinibox_volumes])
                [self.delete_cinder_object(item) for item in cinder_volumes]

    def test_create_volumes_from_different_pools(self):
        with self.provisioning_pool_context() as first:
            with self.provisioning_pool_context() as second:
                with self.cinder_volume_context(1, pool=first), self.cinder_volume_context(1, pool=second):
                    self.assertEquals(1, len(self.infinipy.objects.Volume.find(pool_id=first.get_id())))
                    self.assertEquals(1, len(self.infinipy.objects.Volume.find(pool_id=second.get_id())))

    def assert_cinder_mapping(self, cinder_volume, infinibox_volume):
        from infi.storagemodel import get_storage_model
        from infi.storagemodel.vendor.infinidat.predicates import InfinidatVolumeExists, InfinidatVolumeDoesNotExist
        predicate_args = self.infinipy.get_serial(), infinibox_volume.get_id()
        with self.cinder_mapping_context(cinder_volume):
            for mapping in infinibox_volume.get_luns():
                [host] = self.infinipy.objects.Host.find(id=mapping['host_id'])
                self.assert_host_metadata(host)
            get_storage_model().rescan_and_wait_for(InfinidatVolumeExists(*predicate_args))
        get_storage_model().rescan_and_wait_for(InfinidatVolumeDoesNotExist(*predicate_args))

    def assert_basic_metadata(self, infinibox_object):
        from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver
        metdata = infinibox_object.get_metadata()
        for key, value in dict(system="openstack", driver_version=InfiniboxVolumeDriver.VERSION).items():
            self.assertEquals(metdata[key], str(value))

    def assert_host_metadata(self, infinibox_host):
        from infinidat_openstack.cinder.volume import get_os_hostname, get_os_platform, get_powertools_version
        self.assert_basic_metadata(infinibox_host)
        metdata = infinibox_host.get_metadata()
        for key, value in dict(hostname=get_os_hostname(), platform=get_os_platform(),
                               powertools_version=get_powertools_version()).items():
            self.assertEquals(metdata[key], str(value))

    def assert_volume_metadata(self, cinder_volume, infinibox_volume):
        self.assert_basic_metadata(infinibox_volume)
        metdata = infinibox_volume.get_metadata()
        for key, value in dict(cinder_id=cinder_volume.id, cinder_display_name=cinder_volume.display_name).items():
            self.assertEquals(metdata[key], str(value))

    def assert_snapshot_metadata(self, cinder_volume, infinibox_volume):
        self.assert_basic_metadata(infinibox_volume)
        self.assert_volume_metadata(cinder_volume, infinibox_volume)
        metdata = infinibox_volume.get_metadata()

    def assert_clone_metadata(self, cinder_volume, infinibox_volume):
        self.assert_basic_metadata(infinibox_volume)
        self.assert_volume_metadata(cinder_volume, infinibox_volume)
        metdata = infinibox_volume.get_metadata()
        for key, value in dict(delete_parent=True).items():
            self.assertEquals(metdata[key], str(value))

    def test_volume_mapping(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    self.assert_volume_metadata(cinder_volume, infinibox_volume)
                    self.assert_cinder_mapping(cinder_volume, infinibox_volume)

    def test_create_snapshot(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    with self.cinder_snapshot_context(cinder_volume) as cinder_snapshot:
                        [infinibox_snapshot] = infinibox_volume.get_snapshots()
                        self.assert_snapshot_metadata(cinder_snapshot, infinibox_snapshot)

    def test_create_and_map_clone(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    with self.cinder_clone_context(cinder_volume) as cinder_clone:
                        [infinibox_snapshot] = infinibox_volume.get_snapshots()
                        [infinibox_clone] = infinibox_snapshot.get_clones()
                        self.assert_cinder_mapping(cinder_clone, infinibox_clone)
                        self.assert_clone_metadata(cinder_clone, infinibox_clone)
                        self.assertEquals(infinibox_snapshot.get_metadata()['internal'], "true")

    def test_volume_extend(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    cinder_volume.manager.extend(cinder_volume, 2)  # https://bugs.launchpad.net/python-cinderclient/+bug/1293423
                    self.assert_infinibox_volume_size(infinibox_volume, 2)

    def test_clone_extend(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    with self.cinder_clone_context(cinder_volume) as cinder_clone:
                        [infinibox_snapshot] = infinibox_volume.get_snapshots()
                        [infinibox_clone] = infinibox_snapshot.get_clones()
                        cinder_volume.manager.extend(cinder_clone, 2)  # https://bugs.launchpad.net/python-cinderclient/+bug/1293423
                        self.assert_infinibox_volume_size(infinibox_clone, 2)

    def assert_infinibox_volume_size(self, infinibox_volume, size_in_gb, timeout=30):
        from capacity import GiB
        @retry_func(WaitAndRetryStrategy(timeout, 1))
        def poll():
            self.assertEquals(infinibox_volume.get_size(), size_in_gb * GiB)
        poll()


# HACK: The FibreChannel test should run before the iSCSI test (Nose run the tests alphabetically)

class AAA_ProvisioningTestsMixin_Fibre_Real(test_case.OpenStackFibreChannelTestCase, test_case.RealTestCaseMixin, ProvisioningTestsMixin):
    pass


class AAB_ProvisioningTestsMixin_iSCSI_Real(test_case.OpenStackISCSITestCase, test_case.RealTestCaseMixin, ProvisioningTestsMixin):
    pass


class ProvisioningTestsMixin_Mock(test_case.OpenStackFibreChannelTestCase, test_case.MockTestCaseMixin, ProvisioningTestsMixin):
    pass

