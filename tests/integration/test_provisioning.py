import test_case
from infi.unittest import parameters


class ProvisioningTestsMixin(object):
    def test_volume_type_is_registered(self):
        with self.provisioning_pool_context() as pool:
            display_name = "{}/{}".format(self.infinipy.get_name(), pool.get_name())
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

    def test_volume_mapping(self):
        from infi.storagemodel import get_storage_model
        from infi.storagemodel.predicates import ScsiDevicesAreReady
        from infi.storagemodel.vendor.infinidat.predicates import InfinidatVolumeExists
        from infi.storagemodel.vendor.infinidat.shortcuts import get_infinidat_native_multipath_block_devices
        self.zone_localhost_with_infinibox()
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    with self.cinder_mapping_context(cinder_volume):
                        predicate = InfinidatVolumeExists(self.infinipy.get_serial(), infinibox_volume.get_id())
                        get_storage_model().rescan_and_wait_for(predicate)
                    get_storage_model().rescan_and_wait_for(ScsiDevicesAreReady())

    def test_create_snapshot(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    with self.cinder_snapshot_context(cinder_volume):
                        [infinibox_snapshot] = infinibox_volume.get_snapshots()

    def test_create_clone(self):
        raise test_case.SkipTest("not implemented")

    def test_create_and_delete_volume(self):
        raise test_case.SkipTest("not implemented")

    def test_create_and_delete_snapshot(self):
        raise test_case.SkipTest("not implemented")

    def test_create_and_delete_clone(self):
        raise test_case.SkipTest("not implemented")

    def test_snapshot_mapping(self):
        raise test_case.SkipTest("not implemented")

    def test_clone_mapping(self):
        raise test_case.SkipTest("not implemented")

    def test_volume_extend(self):
        raise test_case.SkipTest("not implemented")


class ProvisioningTestsMixin_Mock(test_case.OpenStackTestCase, test_case.MockTestCaseMixin, ProvisioningTestsMixin):
    pass


class ProvisioningTestsMixin_Real(test_case.OpenStackTestCase, test_case.RealTestCaseMixin, ProvisioningTestsMixin):
    pass
