import contextlib
import hashlib
import random
from base64 import b64encode, b64decode
from . import exceptions
MAGIC_VER = 'ENC:1'


def mask(s, k=hashlib.sha512('InF').digest()):
    s += '\x00' * ((16 - len(s) % 16) % 16)
    s1 = random.randint(1, 255)
    return MAGIC_VER + b64encode(chr(s1) + ''.join([chr(ord(c) ^ (ord(k[i % len(k)]) ^ s1)) for i, c in enumerate(s)]))


def unmask(s, k=hashlib.sha512('InF').digest()):
    if not s.startswith(MAGIC_VER):
        return s
    try:
        s = b64decode(s[len(MAGIC_VER):])
    except TypeError:
        return ''
    s1 = ord(s[0])
    return ''.join([chr(ord(c) ^ (ord(k[i % len(k)]) ^ s1)) for i, c in enumerate(s[1:])]).rstrip('\x00')


def is_masked(s):
    return s.startswith(MAGIC_VER) and (len(s) - len(MAGIC_VER)) % 4 == 0


@contextlib.contextmanager
def get_config_parser(filepath="/etc/cinder/cinder.conf", write_on_exit=False):
    from ConfigParser import RawConfigParser
    from logging.handlers import RotatingFileHandler
    try:
        from collections import OrderedDict
    except ImportError:
        from .collections import OrderedDict

    parser = RawConfigParser(dict_type=OrderedDict)
    parser.optionxform = str    # make options case-sensitive
    parser.read(filepath)
    try:
        yield parser
    finally:
        if write_on_exit:
            handler = RotatingFileHandler(filepath, mode='a', maxBytes=0, backupCount=10)
            handler.doRollover()
            with open(filepath, 'w') as fd:
                parser.write(fd)


ENABLED_BACKENDS = dict(section="DEFAULT", option="enabled_backends")
VOLUME_DRIVER = "infinidat_openstack.cinder.InfiniboxVolumeDriver"
SETTINGS = [
    ("address", "san_ip"),
    ("pool_id", "infinidat_pool_id"),
    ("username", "san_login"),
    ("password", "san_password"),
]

def get_enabled_backends(config_parser):
    if not config_parser.has_option(ENABLED_BACKENDS['section'], ENABLED_BACKENDS['option']):
        return []
    value = config_parser.get(ENABLED_BACKENDS['section'], ENABLED_BACKENDS['option']).strip()
    if value:
        return [item.strip() for item in value.split(',') if item.strip()]
    return []


def get_infinibox_sections(config_parser):
    """:returns: a dict mapping of section and values"""
    sections = {}
    for section in config_parser.sections():
        if config_parser.has_option(section, "volume_driver") and config_parser.get(section, "volume_driver") == VOLUME_DRIVER:
            sections[section] = dict(config_parser.items(section))
    return sections


def get_systems(config_parser):
    """:returns: a list of dictionaries"""
    def _get(item, key):
        value = item.get(key, "<undefined>")
        if isinstance(value, basestring) and value.isdigit():
            return int(value)
        return value
    systems = [dict([(setting[0], _get(value, setting[1])) for setting in SETTINGS], key=key)
               for key, value in get_infinibox_sections(config_parser).items()]
    for system in systems:
        if 'password' in system and is_masked(system['password']):
            system['password'] = unmask(system['password'])
    return systems


def get_system(config_parser, address, pool_id):
    for system in get_systems(config_parser):
        if system['address'] == address and system['pool_id'] == pool_id:
            return system


def set_enabled_backends(config_parser, enabled_backends):
    config_parser.set(ENABLED_BACKENDS['section'],ENABLED_BACKENDS['option'], ",".join(enabled_backends))


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


def apply(config_parser, address, pool_name, username, password, thick_provisioning=False, prefer_fc=False, infinidat_allow_pool_not_found=False, infinidat_purge_volume_on_deletion=False):
    from infinipy import System
    from infinidat_openstack.versioncheck import raise_if_unsupported, get_system_version
    system = System(address, username=username, password=password)
    raise_if_unsupported(get_system_version(address, username, password, system))
    pool = system.objects.Pool.get(name=pool_name)
    pool_id = pool.get_id()
    key = "infinibox-{0}-pool-{1}".format(system.get_serial(), pool.get_id())
    enabled = True
    for system in get_systems(config_parser):
        if system['address'] == address and system['pool_id'] == pool_id:
            key = system['key']
            enabled = key in get_enabled_backends(config_parser)
    if not config_parser.has_section(key):
        config_parser.add_section(key)
    config_parser.set(key, "volume_driver", VOLUME_DRIVER)
    for setting in SETTINGS:
        config_parser.set(key, setting[1], locals()[setting[0]])
    config_parser.set(key, 'san_password', mask(password))
    config_parser.set(key, "infinidat_provision_type", "thick" if thick_provisioning else "thin")
    config_parser.set(key, "infinidat_prefer_fc", prefer_fc)
    config_parser.set(key, "infinidat_allow_pool_not_found", infinidat_allow_pool_not_found)
    config_parser.set(key, "infinidat_purge_volume_on_deletion", infinidat_purge_volume_on_deletion)
    if enabled:
        enable(config_parser, key)
    return key


def update_volume_type(cinder_client, volume_backend_name, system_name, pool_name):
    display_name = "[InfiniBox] {0}/{1}".format(system_name, pool_name)
    [volume_type] = [item for item in cinder_client.volume_types.findall()
                     if item.get_keys().get("volume_backend_name") == volume_backend_name
                     or item.name == display_name] or \
                    [cinder_client.volume_types.create(display_name)]
    volume_type.set_keys(dict(volume_backend_name=volume_backend_name))


def delete_volume_type(cinder_client, volume_backend_name):
    [volume_type] = [item for item in cinder_client.volume_types.findall()
                     if item.get_keys().get("volume_backend_name") == volume_backend_name] or [None]
    if volume_type:
        cinder_client.volume_types.delete(volume_type)
