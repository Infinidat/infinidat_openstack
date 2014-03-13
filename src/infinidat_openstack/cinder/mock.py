import logging


class SanDriver(object):
    def __init__(self, *args, **kwargs):
        super(SanDriver, self).__init__()
        self.configuration = kwargs.get('configuration', None)


class CinderException(Exception):
    pass


class InvalidInput(Exception):
    def __init__(self, reason):
        super(InvalidInput, self).__init__(self, reason)
