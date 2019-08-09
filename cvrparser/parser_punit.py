from . import field_parser as fp
from . import parser_organisation
from . import alchemy_tables


class PenhedParserFactory(object):
    """Simple Factory for making parsers for cvr production unit information"""
    def __init__(self, key_store):
        self.key_store = key_store

    def get_static_parser(self):
        """ return parser for static data fields"""
        json_fields = ['enhedsNummer', 'pNummer', 'enhedstype', 'reklamebeskyttet', 'dataAdgang', 'fejlBeskrivelse',
                       'fejlRegistreret', 'fejlVedIndlaesning', 'samtId', 'virkningsaktoer']
        timestamps = ['naermesteFremtidigeDato', 'sidstIndlaest', 'sidstOpdateret']
        table = alchemy_tables.Produktion
        table_columns = [table.enhedsnummer, table.pnummer, table.enhedstype, table.reklamebeskyttet,
                         table.dataadgang, table.fejlbeskrivelse, table.fejlregistreret,
                         table.fejlvedindlaesning, table.samtid, table.virkningsaktoer,
                         table.naermestefremtidigedato, table.sidstindlaest, table.sidstopdateret]
        return fp.StaticParser(table_class=table, json_fields=json_fields,  json_timestamps=timestamps,
                               table_columns=table_columns)

    def get_value_parser(self):
        """ Penhed data parsers that extract the existing values in the data for different 
        information fields and saves them in database 
        """
        vp = fp.ParserList()
        vp.add_listener(fp.ParserFactory.get_branche_parser(self.key_store))
        vp.add_listener(fp.ParserFactory.get_navne_parser(self.key_store))
        vp.add_listener(fp.ParserFactory.get_kontakt_parser(self.key_store))
        # livsforloeb
        vp.add_listener(fp.UploadLivsforloeb())
        # attributter
        vp.add_listener(fp.AttributParser())
        # interval employment
        vp.add_listener(fp.get_upload_employment_year())
        vp.add_listener(fp.get_upload_employment_quarter())
        vp.add_listener(fp.get_upload_employment_month())
        return vp

    def get_dyna_parser(self):
        vp = fp.ParserList()

        # Direct maps
        #virk_relation = ('virksomhedsrelation', 'cvrNummer', 'penhed')
        # navn, binavn
        navn_mapping = self.key_store.get_name_mapping()
        navne = ('navne', 'navn', 'navn', navn_mapping)
        # kontaktinfo
        kontakt_mapping = self.key_store.get_kontakt_mapping()
        # elektroniskpost
        epost = ('elektroniskPost', 'kontaktoplysning', 'elektroniskpost', kontakt_mapping)
        # telefonnummer
        tlf = ('telefonNummer', 'kontaktoplysning', 'telefonnummer', kontakt_mapping)
        # telefaxnummer
        fax = ('telefaxNummer', 'kontaktoplysning', 'telefaxnummer', kontakt_mapping)

        update_parser = fp.UploadMappedUpdates()
        # for item in [hovedbranche, bibranche1, bibranche2, bibranche3]:
        #     UpdateParser.add_mapping(fp.UpdateMapping(*item))
        for item in [navne, epost, tlf, fax]:
            update_parser.add_mapping(fp.UpdateMapping(*item))
        branche_mapping = self.key_store.get_branche_mapping()
        hovedbranche = fp.UpdateMapping(json_field='hovedbranche', key=('branchekode', 'branchetekst'),
                                        field_type='hovedbranche', field_map=branche_mapping)
        bibranche1 = fp.UpdateMapping(json_field='bibranche1', key=('branchekode', 'branchetekst'),
                                        field_type='bibranche1', field_map=branche_mapping)
        bibranche2 = fp.UpdateMapping(json_field='bibranche2', key=('branchekode', 'branchetekst'),
                                        field_type='bibranche2', field_map=branche_mapping)
        bibranche3 = fp.UpdateMapping(json_field='bibranche3', key=('branchekode', 'branchetekst'),
                                        field_type='bibranche3', field_map=branche_mapping)
        update_parser.add_mapping(hovedbranche)
        update_parser.add_mapping(bibranche1)
        update_parser.add_mapping(bibranche2)
        update_parser.add_mapping(bibranche3)

        vp.add_listener(update_parser)
        vp.add_listener(parser_organisation.CompanyOrganisationParser())
        return vp

    