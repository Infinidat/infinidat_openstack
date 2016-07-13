# Copyright 2016 Infinidat Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from pkg_resources import parse_version
from infinidat_openstack.__version__ import __version__
from infinidat_openstack.exceptions import UserException

FIRST_SUPPORTED_VERSION = parse_version('1.5')
FIRST_UNSUPPORTED_VERSION = parse_version('3.1')


class UnsupportedVersion(UserException):
    def __init__(self, version):
        msg = "Infinidat Openstack v{0} does not support InfiniBox v{1}".format(__version__, version)
        super(UnsupportedVersion, self).__init__(msg)


def get_system_version(address, username, password, system):
    # infinisdk does not support InfiniBox-1.4 response style, so we need to use json_rest
    # but, if that fails (e.g. in case of invalid credentials), we want infinisdk exceptions
    from json_rest import JSONRestSender
    j = JSONRestSender("http://{0}".format(address))
    j.set_basic_authorization(username, password)
    try:
        result = j.get('/api/rest/system/version')
    except:
        return system.get_version()
    if isinstance(result, basestring):
        return result
    return result['result']


def is_supported(infinibox_version):
    # To handle stuff like: 3.0.0.3-iscsi-108-i
    infinibox_version = infinibox_version.split('-')[0]

    v = parse_version(infinibox_version)
    return FIRST_SUPPORTED_VERSION <= v < FIRST_UNSUPPORTED_VERSION


def raise_if_unsupported(infinibox_version):
    if not is_supported(infinibox_version):
        raise UnsupportedVersion(infinibox_version)
