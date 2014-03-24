"""infini-openstack v{0}

Usage:
    infini-openstack [options] list
    infini-openstack [options] set <address> <pool-name> <username> <password>
    infini-openstack [options] remove <address> <pool-id>
    infini-openstack [options] enable <address> <pool-id>
    infini-openstack [options] disable <address> <pool-id>
    infini-openstack [options] update (all | <address> <pool-id>)
    infini-openstack (-h | --help)
    infini-openstack (-v | --version)


Options:
    list                                 print information about configured InfiniBox systems
    refresh                              refresh volume types display
    set                                  add or update an existing InfiniBox system to Cinder
    remove                               delete an existing InfiniBox system from Cinder
    enable                               configure Cinder to load driver for this InfiniBox system
    disable                              configure Cinder not to load driver for this InfiniBox system
    update                               update volume type display name to match the pool name
    --config-file=<config-file>          cinder configuration file [default: /etc/cinder/cinder.conf]
    --rc-file=<rc-file>                  openstack rc file [default: ~/keystonerc_admin]
    --dry-run                            don't save changes
"""


import docopt
import sys
import os
import warnings
warnings.catch_warnings(warnings.simplefilter("ignore")).__enter__() # sentinels has deprecation warning


CONFIGURATION_MODIFYING_KWARGS = ("set", "remove", "enable", "disable")
DONE_MESSAGE = "done, restarting cinder-volume service is requires for changes to take effect"
DONE_NO_RESTART_MESSAGE = "done"
TRACEBACK_FILE = sys.stderr
TABLE_HEADER = ["address", "username", "enabled", "status", "system serial", "system name", "pool id", "pool name"]
NO_SYSTEMS_MESSAGE = "no systems configured"


def system_list(config_parser):
    from prettytable import PrettyTable
    from .config import get_systems, get_enabled_backends
    systems = get_systems(config_parser)
    if not systems:
        _print(NO_SYSTEMS_MESSAGE, sys.stderr)
        return
    table = PrettyTable(TABLE_HEADER)  # v0.6.1 installed by openstack does not print empty tables
    backends = get_enabled_backends(config_parser)
    for system in systems:
        status = "connection successul"
        system_serial = system_name = pool_name = 'n/a'
        try:
            infinipy = get_infinipy_for_system(system)
            system_serial = infinipy.get_serial()
            system_name = infinipy.get_name()
            [pool] = infinipy.objects.Pool.find(id=system['pool_id'])
            pool_name = pool.get_name()
        except Exception, error:
            status = error.message
        table.add_row([system['address'], system['username'], system['key'] in backends, status,
                       system_serial, system_name, system['pool_id'], pool_name])
    _print(table)


def parse_environment(text):
    """:returns: a 4tuple (username, password, project, url"""
    return_value = []
    items = [(line.split("=")[0].split()[1], line.split("=")[1])
            for line in text.splitlines()
            if "=" in line and line.startswith("export ")]
    env = dict(items) # no dict comprehension in Python-2.6
    return env["OS_USERNAME"], env["OS_PASSWORD"], env["OS_TENANT_NAME"], env["OS_AUTH_URL"]


def get_cinder_client(rcfile):
    from cinderclient.v1 import client
    with open(os.path.expanduser(rcfile)) as fd:
        args = parse_environment(fd.read())
    return client.Client(*args)


def assert_config_file_exists(config_file):
    if not os.path.exists(os.path.expanduser(config_file)):
        _print("cinder configuration file {0} does not exist".format(config_file), sys.stderr)
        raise SystemExit(1)


def assert_rc_file_exists(config_file):
    if not os.path.exists(os.path.expanduser(config_file)):
        _print("cinder environment file {0} does not exist".format(config_file), sys.stderr)
        raise SystemExit(1)


def get_infinipy_for_system(system):
    return get_infinipy_from_arguments({'<address>':system['address'], '<username>':system['username'],
                                        '<password>':system['password']})


def get_infinipy_from_arguments(arguments):
    from infinipy import System
    from infinidat_openstack.versioncheck import raise_if_unsupported
    address, username, password = arguments.get('<address>'), arguments.get('<username>'), arguments.get('<password>')
    system = System(address, username=username, password=password)
    raise_if_unsupported(system.get_version())
    return system


def handle_commands(arguments, config_file):
    from . import config
    from .exceptions import UserException
    write_on_exit = not arguments.get("--dry-run") and any(arguments[kwarg] for kwarg in CONFIGURATION_MODIFYING_KWARGS)
    address, username, password = arguments.get('<address>'), arguments.get('<username>'), arguments.get('<password>')
    try:
        pool_name, pool_id = arguments.get('<pool-name>'), int(arguments.get("<pool-id>") or 0)
    except ValueError:
        raise UserException("invalid pool id: {0}".format(arguments.get("<pool-id>")))
    try:
        cinder_client = get_cinder_client(arguments['--rc-file'])
    except Exception, error:
        raise RuntimeError("failed to connect to cinder service: {0}".format(error.message or error))
    with config.get_config_parser(config_file, write_on_exit) as config_parser:
        system = config.get_system(config_parser, address, pool_id)
        if arguments['list']:
            return system_list(config_parser)
        elif arguments['set']:
            key = config.apply(config_parser, address, pool_name, username, password)
            if write_on_exit:
                config.update_volume_type(cinder_client, key, get_infinipy_from_arguments(arguments).get_name(), pool_name)
            _print(DONE_MESSAGE, sys.stderr)
        elif arguments['remove']:
            if system is None:
                _print("failed to remove {0}/{1}, not found".format(address, pool_id), sys.stderr)
                sys.exit(1)
            if write_on_exit:
                config.delete_volume_type(cinder_client, system['key'])
            config.disable(config_parser, system['key'])
            config.remove(config_parser, system['key'])
            _print(DONE_MESSAGE, sys.stderr)
        elif arguments['enable']:
            if system is None:
                _print("failed to enable {0}/{1}, not found".format(address, pool_id), sys.stderr)
                sys.exit(1)
            config.enable(config_parser, system['key'])
            infinipy = get_infinipy_from_arguments(arguments)
            [pool] = infinipy.objects.Pool.find(id=pool_id)
            if write_on_exit:
                config.update_volume_type(cinder_client, system['key'], infinipy.get_name(), pool.get_name())
            _print(DONE_MESSAGE, sys.stderr)
        elif arguments['update']:
            if arguments["all"]:
                for _system in config.get_systems(config_parser):
                    infinipy = get_infinipy_for_system(_system)
                    [pool] = infinipy.objects.Pool.find(id=_system['pool_id'])
                    config.update_volume_type(cinder_client, _system['key'], infinipy.get_name(), pool.get_name())
            else:
                if system is None:
                    _print("failed to update {0}/{1}, not found".format(address, pool_id), sys.stderr)
                    sys.exit(1)
                infinipy = get_infinipy_for_system(system)
                [pool] = infinipy.objects.Pool.find(id=system['pool_id'])
                config.update_volume_type(cinder_client, system['key'], infinipy.get_name(), pool.get_name())
            _print(DONE_NO_RESTART_MESSAGE, sys.stderr)
        elif arguments['disable']:
            if system is None:
                _print("failed to disable {0}/{1}, not found".format(address, pool_id), sys.stderr)
                sys.exit(1)
            if write_on_exit:
                config.delete_volume_type(cinder_client, system['key'])
            config.disable(config_parser, system['key'])
            _print(DONE_MESSAGE, sys.stderr)


def _print(text, stream=sys.stdout):
    print >> stream, text


def main(argv=sys.argv[1:]):
    from .__version__ import __version__
    from .exceptions import UserException
    from traceback import print_exception
    from infinipy.system.exceptions import APICommandFailed
    arguments = docopt.docopt(__doc__.format(__version__), argv=argv, version=__version__)
    config_file = arguments['--config-file']
    rc_file = arguments['--rc-file']

    if arguments['-v']:
        print __version__  # we don't use _print so it would act the same as --version which is handled by docopt
        return
    assert_config_file_exists(config_file)
    assert_rc_file_exists(rc_file)
    try:
        return handle_commands(arguments, config_file)
    except SystemExit:
        raise
    except APICommandFailed, error:
        _print("InfiniBox API failed: {0}".format(error.message), sys.stderr)
        raise SystemExit(1)
    except UserException, error:
        _print(error.message or error, sys.stderr)
        raise SystemExit(1)
    except:
        _print("ERROR: Caught unhandled exception", sys.stderr)
        print_exception(*sys.exc_info(), file=TRACEBACK_FILE)
        raise SystemExit(1)
