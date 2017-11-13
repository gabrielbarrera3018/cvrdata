from elasticsearch1 import Elasticsearch
from elasticsearch1_dsl import Search
from collections import defaultdict, namedtuple
import datetime
import ujson as json
import os
import pytz
from .field_parser import utc_transform
from . import Session, config
from . import alchemy_tables
from .bug_report import add_error
from . import data_scanner
from .cvr_download import download_all_dicts_to_file


def get_session():
    return Session()


class CvrConnection(object):
    """ Class for connecting and retrieving data from danish CVR register """
    def __init__(self,  update_address=False):
        """ Sets everything needed for elasticsearch connection to Danish Business Authority for CVR data extraction
        consider moving elastic search connection into __init__

        Args:
        -----
          update_address: bool, determine if parse and insert address as well (slows it down)
        """
        self.url = 'http://distribution.virk.dk:80'
        self.index = 'cvr-permanent'
        self.company_type = 'virksomhed'
        self.penhed_type = 'produktionsenhed'
        self.person_type = 'deltager'
        user = config['cvr_user']
        password = config['cvr_passwd']
        self.datapath = config['datapath']
        self.update_batch_size = 128
        self.source_keymap = {'virksomhed': 'Vrvirksomhed', 'deltager': 'Vrdeltagerperson',
                              'produktionsenhed': 'VrproduktionsEnhed'}
        self.update_address = update_address
        self.address_parser_factory = data_scanner.AddressParserFactory()
        self.elastic_client = Elasticsearch(self.url, http_auth=(user, password), timeout=60, max_retries=10,
                                            retry_on_timeout=True)
        self.elastic_search_scan_size = 128
        self.elastic_search_scroll_time = u'10m'
        self.update_info = namedtuple('update_info', ['samtid', 'sidstopdateret'])
        self.dummy_date = datetime.datetime(year=1001, month=1, day=1, tzinfo=pytz.utc)

    def search_fielgd_val(self, field, value, size=10):
        search = Search(using=self.elastic_client, index=self.index)
        search = search.query('match', **{field: value}).extra(size=size)
        print('field value search ', search.to_dict())
        response = search.execute()
        hits = response.hits.hits
        return hits

    def get_entity(self, enh):
        """ Get CVR info from given entities 
        
        Args:
        -----
          enh: list of CVR ids (enhedsnummer)
        """
        search = Search(using=self.elastic_client, index=self.index)
        search = search.query('ids', values=enh)
        print('enhedsnummer search in cvr:', search.to_dict())
        # generator = search.scan()
        # hits = [x for x in generator]
        response = search.execute()
        hits = response.hits.hits
        return hits

    def get_pnummer(self, pnummer):
        """ Get CVR info from given production unit id 

        Args:
        -----
          pnummer: id of production unit
        """
        search = Search(using=self.elastic_client, index=self.index)
        search = search.query('match', _type=self.penhed_type)
        search = search.query('match', **{'VrproduktionsEnhed.pNummer': pnummer})
        print('pnummer search ', search.to_dict())
        response = search.execute()
        hits = response.hits.hits
        return hits

    def get_cvrnummer(self, cvrnummer):
        """

        :param cvrnummer: int, cvrnumber of company
        :return: dict, data for company
        """
        search = Search(using=self.elastic_client, index=self.index)
        search = search.query('match', **{'Vrvirksomhed.cvrNummer': cvrnummer})
        print('cvr id search: ', search.to_dict())
        response = search.execute()
        hits = response.hits.hits
        return hits

    def update_all(self, resume_cvr_all=False):
        """Update CVR Company Data
        download updates
        perform updates
        """
        session = get_session()
        ud_table = alchemy_tables.Virksomhed
        res = session.query(ud_table).first()
        session.close()
        old_file_used = False
        if res is None or resume_cvr_all:
            filename = os.path.join(self.datapath, 'cvr_all.json')
            if os.path.exists(filename):
                print('Old file {0} found - using it'.format(filename))
                old_file_used = True
            else:
                self.download_all_dicts(filename)
        else:
            updatetime, _, gunits_to_update = self.get_update_time()
            updatetime = updatetime - datetime.timedelta(hours=2)  # just to be sure
            filename = self.download_all_dicts_from_timestamp(updatetime)
            # filename = os.path.join(self.datapath, 'cvr_update.json')
        print('Start Updating Database')
        self.update_from_mixed_file(filename)
        print('Data base updated - update last update time')
        print('Last update time updated')
        if old_file_used and not resume_cvr_all:
            print('Inserted the old files - now update to newest version, i will call myself')
            self.update_all()

    def download_all_dicts(self, filename):
        """
        :return:
        str: filename, datetime: download time, bool: new download or use old file
        """
        print('Download to file name: {0}'.format(filename))
        params = {'scroll': self.elastic_search_scroll_time, 'size': self.elastic_search_scan_size}
        search = Search(using=self.elastic_client, index=self.index)
        search = search.query('match_all')
        search = search.params(**params)
        print('ElasticSearch Download Scan Query: ', search.to_dict())
        download_all_dicts_to_file(filename, search)

    def download_all_dicts_from_timestamp(self, last_updated):
        """
        :param last_updated: str/datetime
        :return:
        str: filename, datetime: download time, bool: new download or use old file
        """
        print('Download Data Write to File')
        filename = os.path.join(self.datapath, 'cvr_update.json'.format(last_updated))
        filename_tmp = '{0}_tmp'.format(filename)
        if os.path.exists(filename):
            "filename exists {0} overwriting".format(filename)
            # return filename
        print('Download updates to file name: {0}'.format(filename))
        params = {'scroll': self.elastic_search_scroll_time, 'size': self.elastic_search_scan_size}
        # Change to download all files
        with open(filename_tmp, 'w') as f:
            for _type in self.source_keymap.values():
                print('Downloading Type {0}'.format(_type))
                search = Search(using=self.elastic_client, index=self.index)
                search = search.query('range', **{'{0}.sidstOpdateret'.format(_type): {'gte': last_updated}})
                search = search.params(**params)
                print('ElasticSearch Download Scan Query: ', search.to_dict())
                generator = search.scan()
                for i, obj in enumerate(generator):
                    json.dump(obj.to_dict(), f)
                    f.write('\n')
                    if (i % 1000) == 0:
                        print('{0} files downloaded'.format(i))
                print('{0} handled:'.format(_type))
        print('Files downloaded - renaming')
        os.rename(filename_tmp, filename)
        print('Updates Downloaded - File {0} written'.format(filename))
        return filename

    def update_entity(self, enh):
        """ Force download and update of given entities
         
        Args: 
        -----
          enh: int, id of entity to update (enhedsnummer) must be of same type, penhed_type, company_type, person_type
        """
        data = self.get_entity(enh)
        types = {x['_type'] for x in data}
        assert len(types) == 1
        data_type = data[0]['_type']
        key = self.source_keymap[data_type]
        dat = [x['_source'][key] for x in data]
        self.update(dat, key)

    def update(self, dicts, _type):
        """ Update given entities 

        Args:
            dicts: list of dictionaries with data
            _type: string, type object to update
        """
        enh = [x['enhedsNummer'] for x in dicts]
        print('Deleting {0}'.format(_type))
        self.delete(enh, _type)
        print('Deleted now Insert')
        try:
            self.insert(dicts, _type)
        except Exception as e:
            print(e)
            print('enh failed', enh)
            raise e
        print('Update Done!')

    def delete(self, enh, _type):
        """ Delete data from given entities
        
        Args:
        -----
        enh: list of company ids (enhedsnummer)
        _type: object type to delete
        """
        # print('Deleting: ', enh)
        delete_table_models = [alchemy_tables.Update,
                               alchemy_tables.Adresseupdate,
                               alchemy_tables.Attributter,
                               alchemy_tables.Livsforloeb,
                               alchemy_tables.AarsbeskaeftigelseInterval,
                               alchemy_tables.KvartalsbeskaeftigelseInterval,
                               alchemy_tables.MaanedsbeskaeftigelseInterval,
                               alchemy_tables.SpaltningFusion]
        if _type == 'Vrvirksomhed':
            static_table = alchemy_tables.Virksomhed
        elif _type == 'VrproduktionsEnhed':
            static_table = alchemy_tables.Produktion
        elif _type == 'Vrdeltagerperson':
            static_table = alchemy_tables.Person
        else:
            print('bad _type: ', _type)
            raise Exception('bad _type')
        delete_table_models.append(static_table)

        # statements = [t.delete().where(t.c.enhedsnummer.in_(enh)) for t in delete_tables]
        session = get_session()
        try:
            for table_model in delete_table_models:
                session.query(table_model.enhedsnummer.in_(enh)).delete(synchronize_session=False)
            session.commit()
        except Exception as e:
            print('Delete Exception:', enh)
            print(e)
            session.rollback()
            raise

    def insert(self, dicts, enh_type):
        """ Insert data from dicts

        Args:
          dicts: list of dicts with cvr data (Danish Business Authority)
          enh_type: cvr object type
        """
        data_parser = data_scanner.DataParser(_type=enh_type)
        data_parser.parse_data(dicts)
        print('value data inserted - start dynamic ')
        data_parser.parse_dynamic_data(dicts)
        print('dynamic data inserted')
        if self.update_address:
            address_parser = self.address_parser_factory.create_parser()
            address_parser.parse_address_data(dicts)
        print('address data inserted/skipped - start static')
        data_parser.parse_static_data(dicts)
        print('static parsed')

    def make_samtid_table(self):
        """ Make mapping from entity id to current version """
        print('Make id -> samtId map: units update status map')
        table_models = [alchemy_tables.Virksomhed, alchemy_tables.Produktion, alchemy_tables.Person]
        enh_samtid_map = defaultdict()
        session = get_session()
        for table in table_models:
            query = session.query(table.enhedsnummer, table.samtid, table.sidstopdateret)
            existing_data = [(x[0], x[1], x[2], x[3]) for x in query.all()]
            tmp = {a: self.update_info(samtid=b, sidstopdateret=c) for (a, b, c) in existing_data}
            enh_samtid_map.update(tmp)
        print('Id map done')
        return enh_samtid_map

    def update_from_mixed_file(self, filename):
        """ splits data in file by type and updates the database

        :param filename: str, filename full path
        :return:
        """
        print('Start Reading From File')
        enh_samtid_map = self.make_samtid_table()
        dummy = self.update_info(samtid=-1, sidstopdateret=self.dummy_date)
        dicts = {x: list() for x in self.source_keymap.values()}
        with open(filename) as f:
            for i, line in enumerate(f):
                if (i % 50000) == 0:
                    print('{0} updates cleared '.format(i))
                raw_dat = json.loads(line)
                keys = raw_dat.keys()
                # assert len(keys) == 1, keys
                dict_type_set = keys & self.source_keymap.values()  # intersects the two key sets
                if len(dict_type_set) != 1:
                    add_error('BAD DICT DOWNLOADED', raw_dat)
                    continue
                dict_type = dict_type_set.pop()
                dat = raw_dat[dict_type]
                enhedsnummer = dat['enhedsNummer']
                samtid = dat['samtId']
                current_update = enh_samtid_map[enhedsnummer] if enhedsnummer in enh_samtid_map else dummy
                if samtid > current_update.samtid:
                    # update if new version - currently or sidstopdateret > current_update.sidstopdateret:
                    dicts[dict_type].append(dat)
                if len(dicts[dict_type]) >= self.update_batch_size:
                    self.update(dicts[dict_type], dict_type)
                    dicts[dict_type].clear()
        for enh_type, _dicts in dicts.items():
            if len(_dicts) > 0:
                self.update(_dicts, enh_type)
        print('file read all updated')

    def get_update_time(self):
        """ Find units that needs updating and their sidstopdateret (last updated) """
        enh_samtid_map = self.make_samtid_table()
        if len(enh_samtid_map) == 0:
            return self.dummy_date, self.dummy_date, []
        dummy = self.update_info(samtid=-1, sidstopdateret=self.dummy_date)
        print('Get update time for all data')
        search = Search(using=self.elastic_client, index=self.index)
        search = search.query('match_all')
        field_list = ['_id'] + ['{0}.sidstOpdateret'.format(key) for key in self.source_keymap.values()] + \
                     ['{0}.samtId'.format(key) for key in self.source_keymap.values()]
        print('field list to get', field_list)
        search = search.fields(fields=field_list)
        params = {'scroll': self.elastic_search_scroll_time, 'size': 10*self.elastic_search_scan_size}
        search = search.params(**params)
        print('ElasticSearch Query: ', search.to_dict())
        generator = search.scan()
        oldest_sidstopdaret = datetime.datetime.utcnow().astimezone(datetime.timezone.utc)
        oldest_enh = None
        oldest_dat = None
        units_to_update = []
        for i, cvr_update in enumerate(generator):
            if (i % 100000) == 0:
                print('{0} units considered'.format(i))
            enhedsnummer = int(cvr_update.meta.id)
            raw_dat = cvr_update.to_dict()
            samtid = None
            sidstopdateret = None
            for k, v in raw_dat.items():
                if k.endswith('samtId'):
                    samtid = v[0]
                if k.endswith('sidstOpdateret'):
                    sidstopdateret = v[0]
            if sidstopdateret is None or samtid is None:
                continue
            current_update = enh_samtid_map[enhedsnummer] if enhedsnummer in enh_samtid_map else dummy
            if samtid > current_update.samtid:
                units_to_update.append(enhedsnummer)
                utc_sidstopdateret = utc_transform(sidstopdateret)
                if utc_sidstopdateret < oldest_sidstopdaret:
                    oldest_enh = enhedsnummer
                    oldest_dat = raw_dat
                    oldest_sidstopdaret = utc_sidstopdateret
        print('oldest sidstopdaret found', oldest_sidstopdaret, oldest_enh, oldest_dat)
        return oldest_sidstopdaret, units_to_update

    def find_missing(self):
        """
        Check if we are missing anything

        :return:
        """
        search = Search(using=self.elastic_client, index=self.index)
        search = search.query('match_all')
        field_list = ['_id']
        search = search.fields(fields=field_list)
        params = {'scroll': self.elastic_search_scroll_time, 'size': 2*self.elastic_search_scan_size}
        search = search.params(**params)
        print('ElasticSearch Query: ', search.to_dict())
        generator = search.scan()
        ids = [x.meta.id for x in generator]
        return ids