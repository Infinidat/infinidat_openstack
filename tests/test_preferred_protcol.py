from infinidat_openstack.cinder import volume
from munch import Munch
from mock import MagicMock


class FakeDriver(volume.InfiniboxVolumeDriver):
    def __init__(self, prefer_fc=False):
        self.configuration = Munch(infinidat_prefer_fc=prefer_fc)


def _case(connector, methods, prefer_fc=False):
    driver = FakeDriver(prefer_fc=prefer_fc)
    driver._handle_connection(methods, None, connector, None, bar=None)


def _assert(*args, **kwargs):
    raise AssertionError()


def test_only_wwpns():
    connector = dict(wwpns=[1])
    methods = Munch(fc=MagicMock(), iscsi=_assert)
    _case(connector, methods)
    methods.fc.assert_called_with(None, connector, None, bar=None)


def test_default():
    connector = dict(wwpns=[1], initiator=1)
    methods = Munch(fc=_assert, iscsi=MagicMock())
    _case(connector, methods)
    methods.iscsi.assert_called_with(None, connector, None, bar=None)


def test_preferred_fc():
    connector = dict(wwpns=[1], initiator=1)
    methods = Munch(fc=MagicMock(), iscsi=_assert)
    _case(connector, methods, True)
    methods.fc.assert_called_with(None, connector, None, bar=None)


def test_only_initiator():
    connector = dict(initiator=[1])
    methods = Munch(fc=_assert, iscsi=MagicMock())
    _case(connector, methods)
    methods.iscsi.assert_called_with(None, connector, None, bar=None)
