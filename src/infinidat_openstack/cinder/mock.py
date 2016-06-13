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
