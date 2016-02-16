"""infini-openstack v{0}

Usage:
    infini-openstack [options] volume-backend list
    infini-openstack [options] volume-backend set <management-address> <username> <password> <pool-name> [--thick-provisioning] [--volume-backend-name=volume_backend_name]
    infini-openstack [options] volume-backend remove <management-address> <pool-id>
    infini-openstack [options] volume-backend enable <management-address> <pool-id>
    infini-openstack [options] volume-backend disable <management-address> <pool-id>
    infini-openstack [options] volume-backend update (all | <management-address> <pool-id>)
    infini-openstack [options] volume-backend rename <management-address> <pool-id> <new-volume-backend-name>
    infini-openstack [options] volume-backend set-protocol (iscsi | fc) <management-address> <pool-id>
    infini-openstack (-h | --help)
    infini-openstack (-v | --version)

Commands:
    list                                 print information about configured InfiniBox volume backends
    refresh                              refresh volume types display
    set                                  add or update an existing InfiniBox volume backend to Cinder
    remove                               delete an existing InfiniBox volume backend from Cinder
    enable                               configure Cinder to load driver for this InfiniBox volume backend
    disable                              configure Cinder not to load driver for this InfiniBox volume backend
    update                               update volume type display name to match the pool name
    rename                               rename an existing volume backend

Options:
    --config-file=<config-file>          cinder configuration file [default: /etc/cinder/cinder.conf]
    --rc-file=<rc-file>                  openstack rc file [default: ~/keystonerc_admin]
    --commit                             commit the changes into cinder's configuration file (also erases the comments inside it)
"""


from __future__ import print_function
import docopt
import sys
import os
import warnings
from . import config
from .exceptions import UserException
warnings.catch_warnings(warnings.simplefilter("ignore")).__enter__()  # sentinels has deprecation warning
with warnings.catch_warnings():
    import infinisdk  # infinisdk import requests, and requests.packagers.urllib3 calls warning.simplefilter


CONFIGURATION_MODIFYING_COMMANDS = ("set", "remove", "enable", "disable", "update", "rename", "set-protocol")
DONE_MESSAGE = "done, please restart cinder-volume service for changes to take effect"
DONE_NO_RESTART_MESSAGE = "done"
TABLE_HEADER = ["address", "username", "enabled", "status", "system serial", "system name", "pool id", "pool name"]
NO_VOLUME_BACKEND_MESSAGE = "no volume backends configured"


def print_done_message(should_restart):
    msg = DONE_MESSAGE if should_restart else DONE_NO_RESTART_MESSAGE
    print(msg, file=sys.stderr)


def get_existing_volume_backend(config_parser, arguments, operation):
    volume_backend = config.get_volume_backend(config_parser, arguments.address, arguments.pool_id)
    if volume_backend is None:
        msg = "failed to {2} '[InfiniBox] {0}/{1}', not found"
        print(msg.format(arguments.address, arguments.pool_id, operation), file=sys.stderr)
        sys.exit(1)
    return volume_backend


def volume_backend_list(config_parser, cinder_client, arguments):
    from prettytable import PrettyTable
    from .config import get_volume_backends, get_enabled_backends
    volume_backends = get_volume_backends(config_parser)
    if not volume_backends:
        print(NO_VOLUME_BACKEND_MESSAGE, file=sys.stderr)
        return
    table = PrettyTable(TABLE_HEADER)  # v0.6.1 installed by openstack does not print empty tables
    backends = get_enabled_backends(config_parser)
    for volume_backend in volume_backends:
        status = "connection successul"
        system_serial = system_name = pool_name = 'n/a'
        try:
            infinisdk = get_infinisdk_for_volume_backend(volume_backend)
            system_serial = infinisdk.get_serial()
            system_name = infinisdk.get_name()
            pool = infinisdk.pools.get(id=volume_backend['pool_id'])
            pool_name = pool.get_name()
        except Exception as error:
            status = error.message
        table.add_row([volume_backend['address'], volume_backend['username'], volume_backend['key'] in backends, status,
                       system_serial, system_name, volume_backend['pool_id'], pool_name])
    print(table)


def volume_backend_set(config_parser, cinder_client, arguments):
    volume_backend_name = arguments.get("--volume-backend-name")
    key = config.apply(config_parser,
                       arguments.address,
                       arguments.pool_name,
                       arguments.username,
                       arguments.password,
                       volume_backend_name,
                       arguments.get("--thick-provisioning"))
    if volume_backend_name and key != volume_backend_name:
        print("This InfiniBox is already configured with a different backend name: {}. "
              "Please use the rename options instead of --volume-backend-name".format(key), file=sys.stderr)
    if arguments.commit:
        _update_cg_policy()
        system_name = get_infinisdk_from_arguments(arguments).get_name()
        config.update_volume_type(cinder_client, key, system_name, arguments.pool_name)
    print_done_message(arguments.commit)


def volume_backend_remove(config_parser, cinder_client, arguments):
    volume_backend = get_existing_volume_backend(config_parser, arguments, "remove")
    if arguments.commit:
        config.delete_volume_type(cinder_client, volume_backend['key'])
    config.disable(config_parser, volume_backend['key'])
    config.remove(config_parser, volume_backend['key'])
    print_done_message(arguments.commit)


def volume_backend_enable(config_parser, cinder_client, arguments):
    volume_backend = get_existing_volume_backend(config_parser, arguments, "enable")
    config.enable(config_parser, volume_backend['key'])
    if arguments.commit:
        infinisdk = get_infinisdk_for_volume_backend(volume_backend)
        pool = infinisdk.objects.pools.get(id=arguments.pool_id)
        config.update_volume_type(cinder_client, volume_backend['key'], infinisdk.get_name(), pool.get_name())
    print_done_message(arguments.commit)


def volume_backend_disable(config_parser, cinder_client, arguments):
    volume_backend = get_existing_volume_backend(config_parser, arguments, "disable")
    if arguments.commit:
        config.delete_volume_type(cinder_client, volume_backend['key'])
    config.disable(config_parser, volume_backend['key'])
    print_done_message(arguments.commit)


def volume_backend_update(config_parser, cinder_client, arguments):
    if arguments.get("all"):
        for _volume_backend in config.get_volume_backends(config_parser):
            infinisdk = get_infinisdk_for_volume_backend(_volume_backend)
            pool = infinisdk.pools.get(id=_volume_backend['pool_id'])
            config.update_volume_type(cinder_client, _volume_backend['key'], infinisdk.get_name(), pool.get_name())
    else:
        volume_backend = get_existing_volume_backend(config_parser, arguments, "update")
        infinisdk = get_infinisdk_for_volume_backend(volume_backend)
        pool = infinisdk.pools.get(id=volume_backend['pool_id'])
        config.update_volume_type(cinder_client, volume_backend['key'], infinisdk.get_name(), pool.get_name())
    print_done_message(should_restart=False)


def volume_backend_rename(config_parser, cinder_client, arguments):
    volume_backend = get_existing_volume_backend(config_parser, arguments, "rename")
    new_backend_name = arguments.get('<new-volume-backend-name>')
    config.rename_backend(cinder_client,
                          config_parser,
                          arguments.address,
                          arguments.pool_id,
                          volume_backend['key'],
                          new_backend_name)
    if arguments.commit:
        infinisdk = get_infinisdk_for_volume_backend(volume_backend)
        pool = infinisdk.objects.pools.get(id=arguments.pool_id)
        config.update_volume_type(cinder_client, new_backend_name, infinisdk.get_name(), pool.get_name())
    print_done_message(arguments.commit)


def volume_backend_set_protocol(config_parser, cinder_client, arguments):
    volume_backend = get_existing_volume_backend(config_parser, arguments, "set protocol")
    prefer_fc = arguments.get('fc')
    config.update_field(config_parser, volume_backend["key"], "infinidat_prefer_fc", prefer_fc)
    print_done_message(arguments.commit)


def parse_environment(text):
    """:returns: a 4tuple (username, password, project, url"""
    items = [(line.split("=")[0].split()[1], line.split("=")[1])
            for line in text.splitlines()
            if "=" in line and line.startswith("export ")]
    env = dict(items)  # no dict comprehension in Python-2.6
    return env["OS_USERNAME"], env["OS_PASSWORD"], env["OS_TENANT_NAME"], env["OS_AUTH_URL"]


def get_cinder_client(rcfile):
    from cinderclient.v1 import client
    with open(os.path.expanduser(rcfile)) as fd:
        args = parse_environment(fd.read())
    return client.Client(*args)


def assert_config_file_exists(config_file):
    if not os.path.exists(os.path.expanduser(config_file)):
        print("cinder configuration file {0} does not exist".format(config_file), file=sys.stderr)
        raise SystemExit(1)


def assert_rc_file_exists(config_file):
    if not os.path.exists(os.path.expanduser(config_file)):
        print("cinder environment file {0} does not exist".format(config_file), file=sys.stderr)
        raise SystemExit(1)


def get_infinisdk_for_volume_backend(volume_backend):
    from munch import Munch
    return get_infinisdk_from_arguments(Munch(volume_backend))


def get_infinisdk_from_arguments(arguments):
    from infinisdk import InfiniBox
    from infinidat_openstack.versioncheck import raise_if_unsupported, get_system_version
    system = InfiniBox(arguments.address, use_ssl=True, auth=(arguments.username, arguments.password))
    raise_if_unsupported(get_system_version(arguments.address, arguments.username, arguments.password, system))
    return system


def translate_arguments(arguments):
    """ return munch with the same keys as "arguments" plus easier attribute access to common arguments """
    from munch import Munch
    result = Munch(arguments)
    result.address = arguments.get("<management-address>")
    result.username = arguments.get("<username>")
    result.password = arguments.get("<password>")
    result.pool_name = arguments.get("<pool-name>")
    result.commit = arguments.get("--commit")
    try:
        result.pool_id = int(arguments.get("<pool-id>") or 0)
    except ValueError:
        raise UserException("invalid pool id: {0}".format(arguments.get("<pool-id>")))
    return result

def handle_commands(arguments, config_file):
    arguments = translate_arguments(arguments)
    configuration_modifying_command = any(arguments.get(kwarg) for kwarg in CONFIGURATION_MODIFYING_COMMANDS)
    if configuration_modifying_command and not arguments.commit:
        print("This is a dry run. To commit the changes into cinder's configuration file, "
              "pass --commit to this script (note: this flag will also erase comments inside "
              "cinder's configuration file).")
    try:
        cinder_client = get_cinder_client(arguments.get('--rc-file'))
    except Exception as error:
        raise RuntimeError("failed to connect to cinder service: {0}".format(error.message or error))
    with config.get_config_parser(config_file, arguments.commit) as config_parser:
        if arguments.get('list'):
            return volume_backend_list(config_parser, cinder_client, arguments)
        elif arguments.get('set'):
            return volume_backend_set(config_parser, cinder_client, arguments)
        elif arguments.get('remove'):
            return volume_backend_remove(config_parser, cinder_client, arguments)
        elif arguments.get('enable'):
            return volume_backend_enable(config_parser, cinder_client, arguments)
        elif arguments.get('disable'):
            volume_backend_disable(config_parser, cinder_client, arguments)
        elif arguments.get('update'):
            return volume_backend_update(config_parser, cinder_client, arguments)
        elif arguments.get('rename'):
            return volume_backend_rename(config_parser, cinder_client, arguments)
        elif arguments.get('set-protocol'):
            return volume_backend_set_protocol(config_parser, cinder_client, arguments)

def _update_cg_policy():
    from re import compile, MULTILINE
    from os import path
    POLICY_FILENAME = '/etc/cinder/policy.json'
    if not path.exists(POLICY_FILENAME):
        return
    policy_data = open(POLICY_FILENAME).read()
    r = compile('"(consistencygroup:\w+)"\s*:\s*"group:nobody"', MULTILINE)
    policy_data = r.sub('"\\1" : ""', policy_data)
    open(POLICY_FILENAME, 'w').write(policy_data)


def main(argv=sys.argv[1:]):
    from .__version__ import __version__
    from traceback import print_exception
    from infinisdk.core.exceptions import APICommandFailed
    from logbook.handlers import NullHandler
    arguments = docopt.docopt(__doc__.format(__version__), argv=argv, version=__version__)
    config_file = arguments.get('--config-file')
    rc_file = arguments.get('--rc-file')

    if arguments.get('-v'):
        print(__version__)
        return
    assert_config_file_exists(config_file)
    assert_rc_file_exists(rc_file)
    with NullHandler():
        try:
            return handle_commands(arguments, config_file)
        except SystemExit:
            raise
        except APICommandFailed as error:
            print("InfiniBox API failed: {0}".format(error.message), file=sys.stderr)
            raise SystemExit(1)
        except UserException as error:
            print(error.message or error, file=sys.stderr)
            raise SystemExit(1)
        except:
            print("ERROR: Caught unhandled exception", file=sys.stderr)
            print_exception(*sys.exc_info(), file=sys.stderr)
            raise SystemExit(1)
