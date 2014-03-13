import logging


class SanDriver(object):
    def __init__(self, *args, **kwargs):
        super(SanDriver, self).__init__()
        self.configuration = kwargs.get('configuration', None)


class CinderException(Exception):
    pass

