import test_case
from infi.unittest import parameters

class ProvisioningTestCase(test_case.OpenStackTestCase):
    def test_create_volume_in_one_pool(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count(1) as get_diff:
                self.get_cinder_client().volumes.create(1)# create volume via cinder
                [volume], _ = get_diff()

    @parameters.iterate("volume_count", [2, 5, 10])
    def test_create_multiple_volumes_in_one_pool(self, volume_count):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count(volume_count) as get_diff:
                for count in range(volume_count):
                    self.get_cinder_client().volumes.create(1)

    def test_create_volumes_from_different_pools(self):
        raise test_case.SkipTest("not implemented")

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
