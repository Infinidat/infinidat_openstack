"""openstack-infinibox-config

Usage:
    openstack-infinibox-config [options] list
    openstack-infinibox-config [options] set <address> <pool-name> <username> <password>
    openstack-infinibox-config [options] remove <address> <pool-name>
    openstack-infinibox-config [options] enable <address> <pool-name>
    openstack-infinibox-config [options] disable <address> <pool-name>
    openstack-infinibox-config -h | --help
    openstack-infinibox-config -v | --version


Options:
    --config-file=<config-file>          cinder configuration file [default: /etc/cinder/cinder.conf]
    --dry-run                            don't save changes
"""

import docopt
import sys
import os

CONFIGURATION_MODIFYING_KWARGS = ("add", "update", "remove", "enable", "disable")


def system_list(config_parser):
    from prettytable import PrettyTable
    from .config import get_systems, get_enabled_backends
    from infinipy import System
    systems = get_systems(config_parser)
    table = PrettyTable(["address", "pool name", "username", "enabled", "status"])
    backends = get_enabled_backends(config_parser)
    for system in systems:
        status = "connection successul"
        try:
            System(system['address'], username=system['username'], password=system['password']).get_name()
        except Exception, error:
            status = error.message
        table.add_row([system['address'], system['pool'], system['username'], system['key'] in backends, status])
    print table


def main(argv=sys.argv[1:]):
    from .__version__ import __version__
    from . import config, exceptions
    from json import dumps
    arguments = docopt.docopt(__doc__, argv=argv, version=__version__)
    config_file = arguments['--config-file']
    write_on_exit = not arguments.get("--dry-run") or any(arguments[kwarg] for kwarg in CONFIGURATION_MODIFYING_KWARGS)
    address, pool = arguments.get('<address>'), arguments.get('<pool-name>')
    username, password = arguments.get('<username>'), arguments.get('<password>')
    if not os.path.exists(config_file):
        print "configuration file {0} does not exist".format(config_file), sys.stderr
        sys.exit(1)
    try:
        with config.get_config_parser(config_file, write_on_exit) as config_parser:
            if arguments['list']:
                return system_list(config_parser)
            elif arguments['set']:
                config.apply(config_parser, address, pool, username, password)
            elif arguments['remove']:
                system = config.get_system(config_parser, address, pool)
                if system is None:
                    return
                config.diable(config_parser, system['<key>'])
                config.remove(config_parser, system['<key>'])
            elif arguments['enable']:
                system = config.get_system(config_parser, address, pool)
                if system is None:
                    print "failed to enable {0}/{1}, not found".format(address, pool), sys.stderr
                    sys.exit(1)
                config.enable(config_parser, system['<key>'])
            elif arguments['disable']:
                system = config.get_system(config_parser, address, pool)
                if system is None:
                    print "failed to disable {0}/{1}, not found".format(address, pool), sys.stderr
                    sys.exit(1)
                config.disable(config_parser, system['<key>'])
    except exceptions.UserException, error:
        print error.message
        sys.exit(1)
