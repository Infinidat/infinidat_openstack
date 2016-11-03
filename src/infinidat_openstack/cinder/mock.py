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

class VolumeDriver(object):
    def __init__(self, *args, **kwargs):
        super(VolumeDriver, self).__init__()
        self.configuration = kwargs.get('configuration', None)

    def get_version(self):
        return self.VERSION


class CinderException(Exception):
    pass


class InvalidInput(Exception):
    def __init__(self, reason):
        super(InvalidInput, self).__init__(self, reason)


class VolumeIsBusy(Exception):
    def __init__(self, volume_name):
        super(VolumeIsBusy, self).__init__(self, volume_name)

class SnapshotIsBusy(Exception):
    def __init__(self, snapshot_name):
        super(SnapshotIsBusy, self).__init__(self, snapshot_name)

def translate(message):
    return message
