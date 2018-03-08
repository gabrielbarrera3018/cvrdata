from sqlalchemy import tuple_
from . import create_session, engine
from contextlib import closing
from .bug_report import add_error

class MyCache(object):
    """ Change to use async inserts perhaps - that would be neat
    https://further-reading.net/2017/01/quick-tutorial-python-multiprocessing/
    """
    def insert(self, val):
        raise NotImplementedError('Overwrite me please')

    def commit(self):
        raise NotImplementedError('Overwrite me please')


class SessionCache(MyCache):

    def __init__(self, table_class, columns, batch_size=10000):
        self.columns = columns
        self.fields = [x.name for x in columns]
        self.cache = []
        self.batch_size = batch_size
        self.table_class = table_class

    def insert(self, val):
        # assert type(val) is tuple
        self.cache.append(val)
        # if len(self.cache) >= self.batch_size:
        #     self.commit()


class SessionInsertCache(SessionCache):
    """ Make new Cache on with keystore one without
       Wrap session around keystore.update
    """

    def __init__(self, table_class, columns,  batch_size=10000):
        super().__init__(table_class, columns, batch_size)

    def commit(self):
        z = [{x: y for (x, y) in zip(self.fields, c)} for c in self.cache]
        # objs = [self.table_class(**d) for d in z]
        # self.session.add_all(objs)
        # t0 = time.time()
        with closing(create_session()) as session:
            session.bulk_insert_mappings(self.table_class, z, render_nulls=True)
            session.commit()
        # t1 = time.time()
        # total = t1 - t0
        # print('insert cache', self.table_class)
        self.cache = []


class SessionKeystoreCache(SessionCache):
    def __init__(self, table_class, columns, keystore, batch_size=10000):
        super().__init__(table_class, columns, batch_size)
        self.keystore = keystore

    def commit(self):
        # t0 = time.time()
        # session = create_session()
        # does not update the keystore which may be a problem

        while True:
            missing = sorted(self.keystore.update())
            session = create_session()
            try:
                z = [{x: y for (x, y) in zip(self.fields, c)} for (key, c) in self.cache if key in missing]
                session.bulk_insert_mappings(self.table_class, z, render_nulls=True)
                session.commit()
                break
            except Exception as e:
                add_error('SessionKeyStoreCache: \n{0}'.format(e))
                session.rollback()
            finally:
                session.close()
        # t1 = time.time()
        # total = t1 - t0
        # print('keystore cache', self.table_class)
        self.cache = []


class SessionUpdateCache(SessionCache):
    """ Simple class for insert on duplicate replace on a specific key set
        It is implemented as simply delete all, insert again
        Inserts must be of the form (key, data)
        where data should not include the key
    """

    def __init__(self, table_class, key_columns, data_columns, batch_size=10000):
        super().__init__(table_class, key_columns+data_columns, batch_size)
        self.key_columns = key_columns
        self.data_columns = data_columns

    def commit(self):
        """ It not exists insert, else update
        Has deadlock issue since we delete then insert.
        """
        if len(self.cache) == 0:
            return
        # print('update cache', self.table_class, 'pid', os.getpid())
        self.cache = sorted(self.cache)
        keys = [x for (x, y) in self.cache]
        # delete all keys
        flatten_dat = [x+y for (x, y) in self.cache]
        z = [{x: y for (x, y) in zip(self.fields, c)} for c in flatten_dat]
        session = create_session()
        while True:
            try:
                session.query(self.table_class).with_lockmode('update').filter(tuple_(*self.key_columns).in_(keys)).delete(synchronize_session=False)
                session.bulk_insert_mappings(self.table_class, z, render_nulls=True)
                session.commit()
                break
            except Exception as e:
                session.rollback()
                add_error('SessionUpdateCache: \n{0}'.format(e))
                #  logging.info('Deadlock issue in delete insert - RETRY\n{0}'.format(e))
            finally:
                session.close()
        self.cache = []
