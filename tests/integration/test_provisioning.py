import test_case
from tests.test_common import is_devstack
from infi.unittest import parameters, SkipTest
from infi.pyutils.retry import retry_func, WaitAndRetryStrategy
from infi.pyutils.contexts import contextmanager
from time import sleep

try:
    from cinder import exception
except (ImportError, NameError):  # importing with just python hits NameError from the san module, the _ trick
    from infinidat_openstack.cinder import mock as exception

class ProvisioningTestsMixin(object):
    def test_volume_type_is_registered(self):
        with self.provisioning_pool_context() as pool:
            display_name = "[InfiniBox] {}/{}".format(self.infinisdk.get_name(), pool.get_name())
            volume_backend_name = "infinibox-{}-pool-{}".format(self.infinisdk.get_serial(), pool.get_id())
            [volume_type] = [item for item in self.get_cinder_client().volume_types.findall()
                             if item.get_keys()["volume_backend_name"] == volume_backend_name]
            self.assertEquals(volume_type.name, display_name)

    def test_create_volume_in_one_pool(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    self.assertEquals(cinder_volume.id, infinibox_volume.get_metadata_value("cinder_id"))

    @parameters.iterate("volume_count", [2, 5])
    def test_create_multiple_volumes_in_one_pool(self, volume_count):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                cinder_volumes = [self.create_volume(1, pool=pool) for volume in range(volume_count)]
                infinibox_volumes, _ = get_diff()
                self.assertEquals([item.id for item in cinder_volumes],
                                  [item.get_metadata_value("cinder_id") for item in infinibox_volumes])
                [self.delete_cinder_object(item) for item in cinder_volumes]

    def test_create_volumes_from_different_pools(self):
        with self.provisioning_pool_context(total_pools_count=2) as first:
            with self.provisioning_pool_context(total_pools_count=2) as second:
                with self.cinder_volume_context(1, pool=first), self.cinder_volume_context(1, pool=second):
                    self.assertEquals(1, len(self.infinisdk.volumes.find(pool_id=first.get_id())))
                    self.assertEquals(1, len(self.infinisdk.volumes.find(pool_id=second.get_id())))

    def assert_cinder_mapping(self, cinder_volume, infinibox_volume):
        predicate_args = self.infinisdk.get_serial(), infinibox_volume.get_id()
        with self.cinder_mapping_context(cinder_volume):
            for mapping in infinibox_volume.get_logical_units().luns:
                host = mapping.get_host()
                self.assert_host_metadata(host)

    def assert_basic_metadata(self, infinibox_object):
        from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver
        metdata = infinibox_object.get_all_metadata()
        for key, value in dict(system="openstack", driver_version=InfiniboxVolumeDriver.VERSION).items():
            self.assertEquals(metdata[key], str(value))

    def assert_host_metadata(self, infinibox_host):
        from infinidat_openstack.cinder.volume import get_os_hostname, get_os_platform, get_powertools_version
        self.assert_basic_metadata(infinibox_host)
        metdata = infinibox_host.get_all_metadata()
        for key, value in dict(hostname=get_os_hostname(), platform=get_os_platform(),
                               powertools_version=get_powertools_version()).items():
            self.assertEquals(metdata[key], str(value))

    def assert_volume_metadata(self, cinder_volume, infinibox_volume):
        self.assert_basic_metadata(infinibox_volume)
        metdata = infinibox_volume.get_all_metadata()
        for key, value in dict(cinder_id=cinder_volume.id, cinder_display_name=cinder_volume.display_name).items():
            self.assertEquals(metdata[key], str(value))

    def assert_snapshot_metadata(self, cinder_volume, infinibox_volume):
        self.assert_basic_metadata(infinibox_volume)
        self.assert_volume_metadata(cinder_volume, infinibox_volume)
        metdata = infinibox_volume.get_all_metadata()

    def assert_clone_metadata(self, cinder_volume, infinibox_volume):
        self.assert_basic_metadata(infinibox_volume)
        self.assert_volume_metadata(cinder_volume, infinibox_volume)
        metdata = infinibox_volume.get_all_metadata()
        for key, value in dict(delete_parent=True).items():
            self.assertEquals(metdata[key], str(value))

    def test_volume_mapping(self):
        with self._cinder_debug_context():
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
                        [infinibox_clone] = infinibox_snapshot.get_children()
                        self.assert_cinder_mapping(cinder_clone, infinibox_clone)
                        self.assert_clone_metadata(cinder_clone, infinibox_clone)
                        self.assertEquals(infinibox_snapshot.get_all_metadata()['internal'], "true")

    def test_volume_extend(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    cinder_volume.manager.extend(cinder_volume, 2)  # https://bugs.launchpad.net/python-cinderclient/+bug/1293423
                    self.wait_for_object_extending_operation_to_complete(cinder_volume, 60)
                    self.assert_infinibox_volume_size(infinibox_volume, 2)

    def test_clone_extend(self):
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    with self.cinder_clone_context(cinder_volume) as cinder_clone:
                        [infinibox_snapshot] = infinibox_volume.get_snapshots()
                        [infinibox_clone] = infinibox_snapshot.get_children()
                        cinder_volume.manager.extend(cinder_clone, 2)  # https://bugs.launchpad.net/python-cinderclient/+bug/1293423
                        self.wait_for_object_extending_operation_to_complete(cinder_clone, 60)
                        self.assert_infinibox_volume_size(infinibox_clone, 2)

    def test_delete_volume_with_snapshots(self):
        if not isinstance(self, test_case.MockTestCaseMixin):
            raise SkipTest("This test is meant to test the mock configuration")
        with self.provisioning_pool_context() as pool:
            with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                with self.cinder_snapshot_context(cinder_volume) as cinder_snapshot:
                    def delete_volume():
                        self.delete_cinder_object(cinder_volume)
                    self.assertRaises(exception.VolumeIsBusy, delete_volume)

    def test_delete_snapshot_with_clones(self):
        if not isinstance(self, test_case.MockTestCaseMixin):
            raise SkipTest("This test is meant to test the mock configuration")
        with self.provisioning_pool_context() as pool:
            with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                with self.cinder_snapshot_context(cinder_volume) as cinder_snapshot:
                    with self.cinder_volume_from_snapshot_context(cinder_snapshot) as cinder_clone:
                        def delete_snapshot():
                            self.delete_cinder_object(cinder_snapshot)
                        self.assertRaises(exception.SnapshotIsBusy, delete_snapshot)

    def assert_infinibox_volume_size(self, infinibox_volume, size_in_gb, timeout=30):
        from capacity import GiB
        @retry_func(WaitAndRetryStrategy(timeout, 1))
        def poll():
            infinibox_volume.refresh()
            self.assertEquals(infinibox_volume.get_size(), size_in_gb * GiB)
        poll()

    def _do_image_copy_and_assert_size(self, pool, image, count=1):
        with self.assert_volume_count() as get_diff:
            with self.cinder_image_context(1, pool=pool, image=image, count=count):
                infinibox_volumes, _ = get_diff()
                # the right way is to look at the used size, but infinisim's consume updates only the allocated
                # so instead we provision a thin volume here that its initial allocated value is 0 and not the volume size
                # and assert that the image copy changed the allocation size
                for infinibox_volume in infinibox_volumes:
                    self.assertGreater(infinibox_volume.get_allocated(), 0)
                    self.assertLess(infinibox_volume.get_allocated(), infinibox_volume.get_size())

    def _set_cinder_config_values(self, **kwargs):
        from infinidat_openstack.config import get_config_parser
        with get_config_parser(write_on_exit=True) as config_parser:
            for key, value in kwargs.items():
                config_parser.set("DEFAULT", key, str(value))
        test_case.restart_cinder(cinder_volume_only=False)

    def _set_cinder_config_value(self, key, value):
        self._set_cinder_config_values(**dict(key=value))

    def _set_multipath_for_image_xfer(self, value):
        self._set_cinder_config_value("use_multipath_for_image_xfer", value)

    @contextmanager
    def _use_multipath_for_image_xfer_context(self):
        self._set_cinder_config_value("use_multipath_for_image_xfer", "true")
        try:
            yield
        finally:
            self._set_cinder_config_value("use_multipath_for_image_xfer", "false")

    @contextmanager
    def _cinder_debug_context(self):
        self._set_cinder_config_value("debug", "true")
        try:
            yield
        finally:
            self._set_cinder_config_value("debug", "false")

    def test_copy_image_to_volume(self):
        cirrus_image = self.get_cirros_image()
        with self.provisioning_pool_context(provisioning='thin') as pool:
            self._do_image_copy_and_assert_size(pool, cirrus_image)
            with self._use_multipath_for_image_xfer_context():
                self._do_image_copy_and_assert_size(pool, cirrus_image)

    @contextmanager
    def _cinder_quota_context(self, count):
        self._set_cinder_config_values(use_default_quota_class="false",
                                       quota_volumes=count)
        try:
            # TODO these assertions do not work
            #assert self.get_cinder_client().quotas.defaults('admin').volumes == count
            #assert self.get_cinder_client().quotas.get('admin').volumes == count
            yield
        finally:
            self._set_cinder_config_values(use_default_quota_class="true",
                                           quota_volumes=10)

    def test_create_fifty_image_copies(self):
        # TODO chaning the quota doesn't really work on devstack
        num_copies = 10 if is_devstack() else 50
        cirrus_image = self.get_cirros_image()
        with self.provisioning_pool_context(provisioning='thin') as pool:
            with self._use_multipath_for_image_xfer_context():
                with self._cinder_quota_context(num_copies):
                    self._do_image_copy_and_assert_size(pool, cirrus_image, num_copies)

    def test_create_volume_different_backend_name(self):
        if isinstance(self, test_case.MockTestCaseMixin):
            raise SkipTest("This test is meant to test the real configuration")
        with self.provisioning_pool_context(volume_backend_name="kuku") as pool:
            sleep(30) # HACK: The wait_for_type_creation logic doesn't work in test_create_volume_different_backend_name.
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                    [infinibox_volume], _ = get_diff()
                    self.assertEquals(cinder_volume.id, infinibox_volume.get_metadata_value("cinder_id"))

    def test_create_volume_rename_backend_name(self):
        if isinstance(self, test_case.MockTestCaseMixin):
            raise SkipTest("This test is meant to test the real configuration")
        with self.provisioning_pool_context() as pool:
            with self.assert_volume_count() as get_diff:
                with self.cinder_volume_context(1, pool=pool) as cinder_volume_1:
                    [infinibox_volume], _ = get_diff()
                    old_name = "infinibox-{}-pool-{}".format(self.infinisdk.get_serial(), pool.get_id())
                    with self.rename_backend_context(self.infinisdk.get_name(), pool.get_id(), old_name, "bla"):
                        sleep(30) # HACK: We wait after restarting cinder because this test doesn't pass somtimes
                        self.assertEquals(self.get_cinder_client().volume_types.findall()[0].get_keys()["volume_backend_name"], "bla")
                        with self.cinder_volume_context(1, pool=pool) as cinder_volume_2:
                            self.assertEquals(cinder_volume_1.status, 'available')
                            self.assertEquals(cinder_volume_2.status, 'available')


class ProvisioningTestsMixin_Fibre_Real(test_case.OpenStackFibreChannelTestCase, test_case.RealTestCaseMixin, ProvisioningTestsMixin):
    pass


class ProvisioningTestsMixin_iSCSI_Real(test_case.OpenStackISCSITestCase, test_case.RealTestCaseMixin, ProvisioningTestsMixin):
    pass


class ProvisioningTestsMixin_Mock(test_case.MockTestCaseMixin, ProvisioningTestsMixin):
    def _set_cinder_config_values(self, **kwargs):
        pass

    def test_repeating_call_to_initialize_connection(self):
        with self.provisioning_pool_context() as pool:
            with self.cinder_volume_context(1, pool=pool) as cinder_volume:
                with self.cinder_mapping_context(cinder_volume) as first_call:
                    connector = self.get_connector()
                    second_call = cinder_volume.initialize_connection(cinder_volume, connector)
                    self.assertEquals(first_call, second_call)
