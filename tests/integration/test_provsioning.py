import test_case
from infi.unittest import parameters

class ProvisioningTestsMixin(object):
    def test_create_volume_in_one_pool(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count(1) as get_diff:
                cinder_volume = self.create_volume(1)
                [infinibox_volume], _ = get_diff()

    @parameters.iterate("volume_count", [2, 5, 10])
    def test_create_multiple_volumes_in_one_pool(self, volume_count):
        raise test_case.SkipTest("not implemented")

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


class ProvisioningTestsMixin_Mock(test_case.OpenStackTestCase, test_case.MockTestCaseMixin, ProvisioningTestsMixin):
    pass


class ProvisioningTestsMixin_Real(test_case.OpenStackTestCase, test_case.RealTestCaseMixin, ProvisioningTestsMixin):
    pass
