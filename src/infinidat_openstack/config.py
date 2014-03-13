import contextlib
from . import exceptions

@contextlib.contextmanager
def get_config_parser(filepath="/etc/cinder/cinder.conf", write_on_exit=False):
    from ConfigParser import RawConfigParser
    from logging.handlers import RotatingFileHandler
    parser = RawConfigParser()
    parser.optionxform = str    # make options case-sensitive
    parser.read(filepath)
    try:
        yield parser
    finally:
        if write_on_exit:
            handler = RotatingFileHandler(filepath, mode='w', maxBytes=0, backupCount=10)
            handler.doRollover()
            handler.stream.close()
            with open(filepath, 'w') as fd:
                parser.write(fd)


ENABLED_BACKENDS = dict(section="DEFAULT", option="enabled_backends")
VOLUME_DRIVER = "infinidat_openstack.cinder.InfiniboxVolumeDriver"
SETTINGS = [
    ("address", "san_ip"),
    ("pool", "infinidat_pool"),
    ("username", "san_login"),
    ("password", "san_password"),
]

def get_enabled_backends(config_parser):
    if not config_parser.has_option(ENABLED_BACKENDS['section'], ENABLED_BACKENDS['option']):
        return []
    return config_parser.get(ENABLED_BACKENDS['section'], ENABLED_BACKENDS['option']).split()


def get_infinibox_sections(config_parser):
    """:returns: a dict mapping of section and values"""
    sections = {}
    for section in config_parser.sections():
        if config_parser.has_option(section, "volume_driver") and config_parser.get(section, "volume_driver") == VOLUME_DRIVER:
            sections[section] = dict(config_parser.items(section))
    return sections


def get_systems(config_parser):
    """:returns: a list of dictionaries"""
    _get = lambda item, key: item.get(key, "<undefined>")
    return [dict([(setting[0], _get(value, setting[1])) for setting in SETTINGS], key=key)
            for key, value in get_infinibox_sections(config_parser).items()]


def get_system(config_parser, address, pool):
    for system in get_systems(config_parser):
        if system['address'] == address and system['pool'] == pool:
            return system


def set_enabled_backends(config_parser, enabled_backends):
    config_parser.set(ENABLED_BACKENDS['section'],ENABLED_BACKENDS['option'], " ".join(enabled_backends))


def update_enabled_backends(config_parser, key, update_method):
    assert update_method in ('add', 'discard')
    if key not in get_infinibox_sections(config_parser):
        raise exceptions.UserException("cannot enable non-existing {0}".format(key))
    keys = set(get_enabled_backends(config_parser))
    getattr(keys, update_method)(key)
    set_enabled_backends(config_parser, sorted(list(keys)))


def enable(config_parser, key):
    if key not in get_infinibox_sections(config_parser):
        raise exceptions.UserException("cannot enable non-existing {0}".format(key))
    update_enabled_backends(config_parser, key, "add")


def disable(config_parser, key):
    if key not in get_infinibox_sections(config_parser):
        raise exceptions.UserException("cannot disable non-existing {0}".format(key))
    update_enabled_backends(config_parser, key, "discard")


def remove(config_parser, key):
    if config_parser.has_section(key):
        config_parser.remove_section(key)


def apply(config_parser, address, pool, username, password):
    key = address + "/" + pool
    enabled = True
    for system in get_systems(config_parser):
        if system['address'] == address and system['pool'] == pool:
            key = system['key']
            enabled = key in get_enabled_backends(config_parser)
    if not config_parser.has_section(key):
        config_parser.add_section(key)
    config_parser.set(key, "volume_driver", VOLUME_DRIVER)
    for setting in SETTINGS:
        config_parser.set(key, setting[1], locals()[setting[0]])
    if enabled:
        enable(config_parser, key)
        key
    return key
