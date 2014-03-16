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
            with self.assert_volume_count(1) as get_diff:
                cinder_volume = self.create_volume(1)
                [infinibox_volume], _ = get_diff()
                self.assertEquals(cinder_volume.id, infinibox_volume.get_metadata("cinder_id"))

    def test_create_volume_in_one_pool__explicit_volume_type(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count(1) as get_diff:
                cinder_volume = self.create_volume(1, pool)
                [infinibox_volume], _ = get_diff()
                self.assertEquals(cinder_volume.id, infinibox_volume.get_metadata("cinder_id"))

    # @parameters.iterate("volume_count", [2, 5, 10])
    # def test_create_multiple_volumes_in_one_pool(self, volume_count):
    #     with self.provisioning_pool_context() as pool:
    #         with self.assert_volume_count(volume_count) as get_diff:
    #             cinder_volumes = [self.create_volume(1) for volume in range(volume_count)]
    #             infinibox_volumes, _ = get_diff()
    #             self.assertEquals([item.id for item in cinder_volumes],
    #                               [item.get_metadata("cinder_id") for item in infinibox_volumes])

    def test_create_volumes_from_different_pools(self):
        with self.provisioning_pool_context() as first:
            with self.provisioning_pool_context() as second:
                self.create_volume(1, first)
                self.create_volume(1, second)
                self.assertEquals(1, len(self.infinipy.objects.Volume.find(pool_id=first.get_id())))
                self.assertEquals(1, len(self.infinipy.objects.Volume.find(pool_id=second.get_id())))

    def test_volume_mapping(self):
        raise test_case.SkipTest("not implemented")

    def test_create_snapshot(self):
        raise test_case.SkipTest("not implemented")

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
