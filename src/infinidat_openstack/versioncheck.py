from pkg_resources import parse_version
from infinidat_openstack.__version__ import __version__
from infinidat_openstack.exceptions import UserException

FIRST_SUPPORTED_VERSION = parse_version('1.5')
FIRST_UNSUPPORTED_VERSION = parse_version('1.6')


class UnsupportedVersion(UserException):
    def __init__(self, version):
        msg = "Infinidat Openstack v{0} does not support InfiniBox v{1}".format(__version__, version)
        super(UnsupportedVersion, self).__init__(msg)


def is_supported(infinibox_version):
    v = parse_version(infinibox_version)
    return FIRST_SUPPORTED_VERSION <= v < FIRST_UNSUPPORTED_VERSION


def raise_if_unsupported(infinibox_version):
    if not is_supported(infinibox_version):
        raise UnsupportedVersion(infinibox_version)
