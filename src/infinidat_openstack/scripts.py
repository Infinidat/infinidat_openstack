"""openstack-infinibox-config v{0}

Usage:
    openstack-infinibox-config [options] list
    openstack-infinibox-config [options] set <address> <pool-name> <username> <password>
    openstack-infinibox-config [options] remove <address> <pool-id>
    openstack-infinibox-config [options] enable <address> <pool-id>
    openstack-infinibox-config [options] disable <address> <pool-id>
    openstack-infinibox-config -h | --help
    openstack-infinibox-config -v | --version


Options:
    list                                 print information about configured InfiniBox systems
    set                                  add or update an existing InfiniBox system to Cinder
    remove                               delete an existing InfiniBox system from Cinder
    enable                               configure Cinder to load driver for this InfiniBox system
    disable                              configure Cinder not to load driver for this InfiniBox system
    --config-file=<config-file>          cinder configuration file [default: /etc/cinder/cinder.conf]
    --rc-file=<rc-file>                  openstack rc file [default: ~/keystonerc_admin]
    --dry-run                            don't save changes
"""


import docopt
import sys
import os

CONFIGURATION_MODIFYING_KWARGS = ("set", "remove", "enable", "disable")
DONE_MESSAGE = "done, restarting cinder-volume service is requires for changes to take effect"


def system_list(config_parser):
    from prettytable import PrettyTable
    from .config import get_systems, get_enabled_backends
    from infinipy import System
    systems = get_systems(config_parser)
    table = PrettyTable(["address", "username", "enabled", "status", "system serial", "system name", "pool id", "pool name"])
    backends = get_enabled_backends(config_parser)
    for system in systems:
        status = "connection successul"
        system_serial = system_name = pool_name = 'n/a'
        try:
            infinipy = System(system['address'], username=system['username'], password=system['password'])
            system_serial = infinipy.get_serial()
            system_name = infinipy.get_name()
            [pool] = infinipy.objects.Pool.find(id=system['pool_id'])
            pool_name = pool.get_name()
        except Exception, error:
            status = error.message
        table.add_row([system['address'], system['username'], system['key'] in backends, status,
                       system_serial, system_name, system['pool_id'], pool_name])
    print table


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


def ignore_warnings():
    import warnings
    warnings.catch_warnings(warnings.simplefilter("ignore")).__enter__() # sentinels has deprecation warning


def assert_config_file_exists(config_file):
    if not os.path.exists(config_file):
        print >> sys.stderr, "cinder configuration file {0} does not exist".format(config_file)
        raise SystemExit(1)


def get_infinipy_from_arguments(arguments):
    from infinipy import System
    address, username, password = arguments.get('<address>'), arguments.get('<username>'), arguments.get('<password>')
    return System(address, username=username, password=password)


def handle_commands(arguments, config_file):
    from . import config
    write_on_exit = not arguments.get("--dry-run") and any(arguments[kwarg] for kwarg in CONFIGURATION_MODIFYING_KWARGS)
    address, username, password = arguments.get('<address>'), arguments.get('<username>'), arguments.get('<password>')
    pool_name, pool_id = arguments.get('<pool-name>'), int(arguments.get("<pool-id>") or 0)
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
            print >> sys.stderr, DONE_MESSAGE
        elif arguments['remove']:
            if system is None:
                return
            config.disable(config_parser, system['key'])
            if write_on_exit:
                config.delete_volume_type(cinder_client, system['key'])
            config.remove(config_parser, system['key'])
            print >> sys.stderr, DONE_MESSAGE
        elif arguments['enable']:
            if system is None:
                print >> sys.stderr, "failed to enable {0}/{1}, not found".format(address, pool_id)
                sys.exit(1)
            config.enable(config_parser, system['key'])
            infinipy = get_infinipy_from_arguments(arguments)
            [pool] = infinipy.objects.Pool.find(id=pool_id)
            if write_on_exit:
                config.update_volume_type(cinder_client, system['key'], infinipy.get_name(), pool.get_name())
            print >> sys.stderr, DONE_MESSAGE
        elif arguments['disable']:
            if system is None:
                print >> sys.stderr, "failed to disable {0}/{1}, not found".format(address, pool_id)
                sys.exit(1)
            if write_on_exit:
                config.delete_volume_type(cinder_client, system['key'])
            config.disable(config_parser, system['key'])
            print >> sys.stderr, DONE_MESSAGE


def main(argv=sys.argv[1:]):
    from .__version__ import __version__
    from .exceptions import UserException
    arguments = docopt.docopt(__doc__.format(__version__), argv=argv, version=__version__)
    config_file = arguments['--config-file']

    ignore_warnings()
    assert_config_file_exists(config_file)
    try:
        return handle_commands(arguments, config_file)
    except SystemExit:
        raise
    except UserException, error:
        print >> sys.stderr, error.message or error

