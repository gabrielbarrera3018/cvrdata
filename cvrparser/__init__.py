import configparser
import getpass

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


config_path = Path(__file__).parent / 'config.ini'

_engine = None
_session = None


class DefaultEngineProxy:
    def __getattr__(self, item):
        return getattr(_engine, item)

    def __setattr__(self, name, value):
        return setattr(_engine, name, value)

    def __delattr__(self, name):
        return delattr(_engine, name)

    def __eq__(self, other):
        return _engine == other

    def __hash__(self):
        return _engine.__hash__()


class DefaultSessionProxy:
    def __getattr__(self, item):
        return getattr(_session, item)

    def __setattr__(self, name, value):
        return setattr(_session, name, value)

    def __delattr__(self, name):
        return delattr(_session, name)

    def __eq__(self, other):
        return _session == other

    def __hash__(self):
        return _engine.__hash__()

    def __call__(self, *args, **kwargs):
        return _session(*args, **kwargs)


config_fields = ['host', 'port', 'user', 'passwd', 'database', 'sql_type', 'cvr_user', 'cvr_passwd', 'charset']


def interactive_configure_connection():
    print('Please enter the database connection information below.')
    print('sql_type is either mysql or postgresql.')
    host = input('Hostname: ')
    port = input('Port: ')
    user = input('User: ')
    passwd = getpass.getpass()
    database = input('Database: ')
    while True:
        sql_type = input('Sql type [1] mysql [2] postgresql: ')
        try:
            sql_type = int(sql_type)
            assert(sql_type in [1, 2])
            sql_type = ['mysql', 'postgresql'][sql_type - 1]
            break
        except (ValueError, AssertionError):
            print('Please enter a number, either 1 or 2')
            continue

    config_values = {
        'Global': dict(
            host=host, port=port, user=user, passwd=passwd, database=database,
            sql_type=sql_type, charset='utf8mb4',
        )
    }
    _config = configparser.ConfigParser()
    _config.read_dict(config_values)
    with open(str(config_path), 'w') as fp:
        _config.write(fp)
    return


def interactive_ensure_config_exists():
    if not config_path.exists():
        print('No configuration file found.')
        interactive_configure_connection()


def read_config(config_name='Global'):
    _config = configparser.ConfigParser()
    with open(str(config_path)) as fp:
        _config.read_file(fp)
        actual_config_fields = _config[config_name].keys()
        missing = set(config_fields) - actual_config_fields
        if missing:
            print('The configuration file (%s) ' % str(config_path) +
                  'is invalid. ' +
                  'Missing fields %s' % (', '.join(map(repr, missing))))
            raise Exception
        return _config


def setup_database_connection(config_name='Global'):
    global _engine, _session

    db_config = read_config()
    connection_url = ("{sql_type}://{user}:{passwd}@{host}:{port}/"
                      "{database}?charset={charset}")
    connection_url = connection_url.format(**db_config[config_name])
    _engine = create_engine(connection_url, encoding='utf8', echo=False)
    _session = sessionmaker(bind=engine)


engine = DefaultEngineProxy()
Session = DefaultSessionProxy()
config = read_config()['Global']


def create_session():
    return Session()