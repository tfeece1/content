import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *

''' IMPORTS '''
from ldap3 import Server, Connection, Tls, BASE
from ldap3.utils.dn import parse_dn
from ldap3.core.exceptions import LDAPBindError, LDAPInvalidDnError, LDAPSocketOpenError, LDAPInvalidPortError
from ssl import CERT_REQUIRED
from typing import Tuple, List

''' OpenLDAP CLIENT '''


class LdapClient:
    """
        Base client for Ldap authentication.

        :type kwargs: ``dict``
        :param kwargs: Initialize params for ldap client
    """

    GROUPS_TOKEN = 'primaryGroupToken'
    GROUPS_MEMBER = 'memberOf'
    GROUPS_PRIMARY_ID = 'primaryGroupID'
    TIMEOUT = 120  # timeout for ssl/tls socket
    DEV_BUILD_NUMBER = 'REPLACE_THIS_WITH_CI_BUILD_NUM'  # is used only in dev mode
    SUPPORTED_BUILD_NUMBER = 57352  # required server build number

    def __init__(self, kwargs):
        self._ldap_server_type = kwargs.get('ldap_server_type', 'OpenLDAP')  # OpenLDAP or Active Directory
        self._host = kwargs.get('host')
        self._port = int(kwargs.get('port')) if kwargs.get('port') else None
        self._username = kwargs.get('credentials', {}).get('identifier', '')
        self._password = kwargs.get('credentials', {}).get('password', '')
        self._base_dn = kwargs.get('base_dn', '').strip()
        self._connection_type = kwargs.get('connection_type', 'none').lower()
        self._fetch_groups = kwargs.get('fetch_groups', True)
        self._verify = not kwargs.get('insecure', False)
        self._ldap_server = self._initialize_ldap_server()
        self._page_size = int(kwargs.get('page_size', 500))
        self._groups_filter_class = kwargs.get('group_filter_class', 'posixGroup').strip()
        self._group_identifier_attribute = kwargs.get('group_identifier_attribute', 'gidNumber').strip()
        self._member_identifier_attribute = kwargs.get('member_identifier_attribute', 'memberUid').strip()
        self._user_filter_class = kwargs.get('user_filter_class', 'posixAccount')
        self._user_identifier_attribute = kwargs.get('user_identifier_attribute', 'uid')
        self._custom_attributes = kwargs.get('custom_attributes', '')
        # TODO: need to check if we can change the instance configuration params according to the selected server type.
        # TODO: if not - worth adding explanation to the descriptions of the params that are relevant only to OpenLDAP.

    @property
    def GROUPS_OBJECT_CLASS(self):
        """
        :rtype: ``str``
        :return: Group's base class object name.
        """
        return self._groups_filter_class

    @property
    def GROUPS_IDENTIFIER_ATTRIBUTE(self):
        """
        :rtype: ``str``
        :return: Groups identifier attribute.
        """
        return self._group_identifier_attribute

    @property
    def GROUPS_MEMBERSHIP_IDENTIFIER_ATTRIBUTE(self):
        """
        :rtype: ``str``
        :return: Groups membership attribute.
        """
        return self._member_identifier_attribute

    @property
    def USER_OBJECT_CLASS(self):
        """
        :rtype: ``str``
        :return: User's base class object name.
        """
        return self._user_filter_class

    @property
    def USER_IDENTIFIER_ATTRIBUTE(self):
        """
        rtype: ``str``
        :return: Users identifier attribute.
        """
        return self._user_identifier_attribute

    @property
    def CUSTOM_ATTRIBUTE(self):
        """
        rtype: ``str``
        :return: User defined attributes.
        """
        return self._custom_attributes

    def _initialize_ldap_server(self):
        """
        Initializes ldap server object with given parameters. Supports both encrypted and non encrypted connection.

        :rtype: ldap3.Server
        :return: Initialized ldap server object.
        """
        if self._connection_type == 'ssl':
            tls = Tls(validate=CERT_REQUIRED,
                      ca_certs_file=os.environ.get('SSL_CERT_FILE')) if self._verify else None
            # if certificate verification isn't required, SSL connection will be used. Otherwise secure connection
            # will be performed over Tls.
            return Server(host=self._host, port=self._port, use_ssl=True, tls=tls, connect_timeout=LdapClient.TIMEOUT)
        else:
            # non encrypted connection initialized
            return Server(host=self._host, port=self._port, connect_timeout=LdapClient.TIMEOUT)

    @staticmethod
    def _parse_ldap_group_entries(ldap_group_entries: List[dict], groups_identifier_attribute: str) -> List[dict]:
        """
            Returns parsed ldap groups entries.
        """
        return [{'DN': ldap_group.get('dn'), 'Attributes': [{'Name': LdapClient.GROUPS_TOKEN,
                                                             'Values': [str(ldap_group.get('attributes', {}).get(
                                                                 groups_identifier_attribute))]}]}
                for ldap_group in ldap_group_entries]

    @staticmethod
    def _parse_ldap_group_entries_and_referrals(ldap_group_entries: List[dict]) -> Tuple[List[str], List[dict]]:
        """
            Returns parsed ldap groups entries and referrals.
        """
        referrals = []
        entries = []

        for ldap_group in ldap_group_entries:
            if ldap_group_type := ldap_group.get('type'):
                if ldap_group_type == 'searchResRef':  # a referral
                    referrals.extend(ldap_group.get('uri'))

                elif ldap_group_type == 'searchResEntry':  # an entry
                    entries.append(
                        {'DN': ldap_group.get('dn'),
                         'Attributes': [{'Name': LdapClient.GROUPS_TOKEN,
                                         'Values': [str(ldap_group.get('attributes', {}).get(LdapClient.GROUPS_TOKEN))]}
                                        ]
                         })
        return referrals, entries

    @staticmethod
    def _parse_ldap_users_groups_entries(ldap_group_entries: List[dict]) -> List[Optional[Any]]:
        """
            Returns parsed user's group entries.
        """
        return [ldap_group.get('dn') for ldap_group in ldap_group_entries]

    @staticmethod
    def _build_entry_for_user(user_groups: str, user_data: dict,
                              mail_attribute: str, name_attribute: str, phone_attribute: str) -> dict:
        """
            Returns entry for specific ldap user.
        """
        parsed_ldap_groups = {'Name': LdapClient.GROUPS_MEMBER, 'Values': user_groups}
        parsed_group_id = {'Name': LdapClient.GROUPS_PRIMARY_ID, 'Values': user_data['gid_number']}
        attributes = [parsed_ldap_groups, parsed_group_id]

        if 'name' in user_data:
            attributes.append({'Name': name_attribute, 'Values': [user_data['name']]})
        if 'email' in user_data:
            attributes.append({'Name': mail_attribute, 'Values': [user_data['email']]})
        if 'mobile' in user_data:
            attributes.append({'Name': phone_attribute, 'Values': [user_data['mobile']]})

        return {
            'DN': user_data['dn'],
            'Attributes': attributes
        }

    @staticmethod
    def _is_valid_dn(dn: str, user_identifier_attribute: str) -> Tuple[bool, str]:
        """
            Validates whether given input is valid ldap DN. Returns flag indicator and user's identifier value from DN.
        """
        try:
            parsed_dn = parse_dn(dn, strip=False)
            for attribute_and_value in parsed_dn:
                if attribute_and_value[0].lower() == user_identifier_attribute.lower():
                    return True, attribute_and_value[1]

            raise Exception(f'OpenLDAP {user_identifier_attribute} attribute was not found in user DN : {dn}')
        except LDAPInvalidDnError as e:
            demisto.debug(f'OpenLDAP failed parsing DN with error: {str(e)}. Fallback for unique id activated')
            return False, dn
        except Exception:
            raise

    def _fetch_all_groups(self):
        """
            Fetches all ldap groups under given base DN.
        """
        with Connection(self._ldap_server, self._username, self._password) as ldap_conn:
            if self._ldap_server_type == 'Active Directory':
                search_filter = '(&(objectClass=group)(objectCategory=group))'
                ldap_group_entries = ldap_conn.extend.standard.paged_search(search_base=self._base_dn,
                                                                            search_filter=search_filter,
                                                                            attributes=[LdapClient.GROUPS_TOKEN],
                                                                            paged_size=self._page_size)

                referrals, entries = LdapClient._parse_ldap_group_entries_and_referrals(ldap_group_entries)

                # Reverse the lists to conform Active Directory Authentication integration's output:
                referrals.reverse()
                entries.reverse()

                return {
                    'Controls': None,
                    'Referrals': referrals,
                    'Entries': entries
                }

            else:  # ldap server is OpenLDAP
                search_filter = f'(objectClass={self.GROUPS_OBJECT_CLASS})'
                ldap_group_entries = ldap_conn.extend.standard.paged_search(search_base=self._base_dn,
                                                                            search_filter=search_filter,
                                                                            attributes=[
                                                                                self.GROUPS_IDENTIFIER_ATTRIBUTE],
                                                                            paged_size=self._page_size)

                return {
                    'Controls': None,
                    'Referrals': ldap_conn.result.get('referrals'),
                    'Entries': LdapClient._parse_ldap_group_entries(ldap_group_entries,
                                                                    self.GROUPS_IDENTIFIER_ATTRIBUTE)
                }

    def _get_formatted_custom_attributes(self) -> str:
        """
        :return: custom attributes parsed to the form (att_name1=value1)(attname2=value2)
        """
        if not self.CUSTOM_ATTRIBUTE:
            return ''
        formatted_attributes = ''
        for att in self.CUSTOM_ATTRIBUTE.split(','):
            if len(att.split('=')) != 2:
                raise Exception(f'User defined attributes must be of the form'
                                f' \"attrA=valA,attrB=valB,...\", but got: {self.CUSTOM_ATTRIBUTE}')
            formatted_attributes = formatted_attributes + f'({att})'
        return formatted_attributes

    def _create_search_filter(self, filter_prefix: str) -> str:
        return filter_prefix + self._get_formatted_custom_attributes()

    def _fetch_specific_groups(self, specific_groups: str) -> dict:
        """
            Fetches specific ldap groups under given base DN.
        """
        dn_list = [group.strip() for group in argToList(specific_groups, separator="#")]
        with Connection(self._ldap_server, self._username, self._password) as ldap_conn:
            if self._ldap_server_type == 'Active Directory':
                dns_filter = ''
                for dn in dn_list:
                    dns_filter += f'(distinguishedName={dn})'
                search_filter = f'(&(objectClass=group)(objectCategory=group)(|{dns_filter}))'

                ldap_group_entries = ldap_conn.extend.standard.paged_search(search_base=self._base_dn,
                                                                            search_filter=search_filter,
                                                                            attributes=[LdapClient.GROUPS_TOKEN],
                                                                            paged_size=self._page_size)

                referrals, entries = LdapClient._parse_ldap_group_entries_and_referrals(ldap_group_entries)

                # Reverse the lists to conform Active Directory Authentication integration's output:
                referrals.reverse()
                entries.reverse()

                return {
                    'Controls': None,
                    'Referrals': referrals,
                    'Entries': entries
                }

            else:  # ldap server is OpenLDAP

                parsed_ldap_entries = []

                for dn in dn_list:
                    search_filter = f'(objectClass={self.GROUPS_OBJECT_CLASS})'
                    ldap_group_entries = ldap_conn.extend.standard.paged_search(search_base=dn,
                                                                                search_filter=search_filter,
                                                                                attributes=[
                                                                                    self.GROUPS_IDENTIFIER_ATTRIBUTE],
                                                                                paged_size=self._page_size,
                                                                                search_scope=BASE)
                    parsed_ldap_entries.append(
                        self._parse_ldap_group_entries(ldap_group_entries, self.GROUPS_IDENTIFIER_ATTRIBUTE))

                return {
                    'Controls': None,
                    'Referrals': ldap_conn.result.get('referrals'),
                    'Entries': parsed_ldap_entries
                }

    @staticmethod
    def _get_ad_username(username: str) -> str:
        """
            Returns the Active Directory username for XSOAR.
        """
        x_username = username
        if '\\' in username:
            x_username = username.split('\\')[1]
        elif '@' in username:
            x_username = username.split('@')[0]

        return x_username

    def get_ldap_groups(self, specific_group: str = '') -> dict:
        """
            Implements ldap groups command.
        """
        instance_name = demisto.integrationInstance()
        if not self._fetch_groups and not specific_group:
            demisto.info(f'Instance [{instance_name}] configured not to fetch groups')
            sys.exit()

        searched_results = self._fetch_specific_groups(
            specific_group) if not self._fetch_groups else self._fetch_all_groups()
        demisto.info(f'Retrieved {len(searched_results["Entries"])} groups from LDAP Authentication {instance_name}')

        return searched_results

    def authenticate_ldap_user(self, username: str, password: str) -> str:
        """
            Performs simple bind operation on ldap server.
        """
        ldap_conn = Connection(server=self._ldap_server, user=username, password=password, auto_bind=True)

        if ldap_conn.bound:
            ldap_conn.unbind()
            return "Done"
        else:
            raise Exception(f"LDAP Authentication - authentication connection failed,"
                            f" server type is: {self._ldap_server_type}")

    def get_user_data(self, username: str, pull_name: bool, pull_mail: bool, pull_phone: bool,
                      name_attribute: str, mail_attribute: str, phone_attribute: str,
                      search_user_by_dn: bool = False) -> dict:
        """
            Returns data for given ldap user.
        """
        with Connection(self._ldap_server, self._username, self._password) as ldap_conn:
            attributes = [self.GROUPS_IDENTIFIER_ATTRIBUTE]

            if pull_name:
                attributes.append(name_attribute)
            if pull_mail:
                attributes.append(mail_attribute)
            if pull_phone:
                attributes.append(phone_attribute)

            if search_user_by_dn:
                search_filter = f'(&(objectClass={self.USER_OBJECT_CLASS})' +\
                                self._get_formatted_custom_attributes() + ')'
                ldap_conn.search(search_base=username, search_filter=search_filter, size_limit=1,
                                 attributes=attributes, search_scope=BASE)
            else:
                custom_attributes = self._get_formatted_custom_attributes()
                search_filter = (f'(&(objectClass={self.USER_OBJECT_CLASS})'
                                 f'({self.USER_IDENTIFIER_ATTRIBUTE}={username}){custom_attributes})')
                ldap_conn.search(search_base=self._base_dn, search_filter=search_filter, size_limit=1,
                                 attributes=attributes)

            if not ldap_conn.entries:
                raise Exception("LDAP Authentication - OpenLDAP user not found")
            entry = ldap_conn.entries[0]

            if self.GROUPS_IDENTIFIER_ATTRIBUTE not in entry \
                    or not entry[self.GROUPS_IDENTIFIER_ATTRIBUTE].value:
                raise Exception(f"LDAP Authentication - OpenLDAP user's {self.GROUPS_IDENTIFIER_ATTRIBUTE} not found")

            user_data = {'dn': entry.entry_dn, 'gid_number': [str(entry[self.GROUPS_IDENTIFIER_ATTRIBUTE].value)],
                         'referrals': ldap_conn.result.get('referrals')}

            if name_attribute in entry and entry[name_attribute].value:
                user_data['name'] = ldap_conn.entries[0][name_attribute].value
            if mail_attribute in entry and entry[mail_attribute].value:
                user_data['email'] = ldap_conn.entries[0][mail_attribute].value
            if phone_attribute in entry and entry[phone_attribute].value:
                user_data['mobile'] = ldap_conn.entries[0][phone_attribute].value

            return user_data

    def get_user_groups(self, user_identifier: str):
        """
            Returns user's group.
        """
        with Connection(self._ldap_server, self._username, self._password) as ldap_conn:
            search_filter = (f'(&(objectClass={self.GROUPS_OBJECT_CLASS})'
                             f'({self.GROUPS_MEMBERSHIP_IDENTIFIER_ATTRIBUTE}={user_identifier}))')
            ldap_group_entries = ldap_conn.extend.standard.paged_search(search_base=self._base_dn,
                                                                        search_filter=search_filter,
                                                                        attributes=[
                                                                            self.GROUPS_IDENTIFIER_ATTRIBUTE],
                                                                        paged_size=self._page_size)
            return LdapClient._parse_ldap_users_groups_entries(ldap_group_entries)

    def authenticate_and_roles_openldap(self, username: str, password: str, pull_name: bool = True,
                                        pull_mail: bool = True, pull_phone: bool = False, mail_attribute: str = 'mail',
                                        name_attribute: str = 'name', phone_attribute: str = 'mobile') -> dict:
        """
            Implements authenticate and roles command for OpenLDAP.
        """
        search_user_by_dn, user_identifier = LdapClient._is_valid_dn(username, self.USER_IDENTIFIER_ATTRIBUTE)
        user_data = self.get_user_data(username=username, search_user_by_dn=search_user_by_dn, pull_name=pull_name,
                                       pull_mail=pull_mail, pull_phone=pull_phone, mail_attribute=mail_attribute,
                                       name_attribute=name_attribute, phone_attribute=phone_attribute)
        self.authenticate_ldap_user(user_data['dn'], password)
        user_groups = self.get_user_groups(user_identifier)

        return {
            'Controls': None,
            'Referrals': user_data['referrals'],
            'Entries': [LdapClient._build_entry_for_user(user_groups=user_groups, user_data=user_data,
                                                         mail_attribute=mail_attribute, name_attribute=name_attribute,
                                                         phone_attribute=phone_attribute)]
        }

    def authenticate_and_roles_active_directory(self, username: str, password: str, pull_name: bool = True,
                                                pull_mail: bool = True, pull_phone: bool = False,
                                                mail_attribute: str = 'mail', name_attribute: str = 'name',
                                                phone_attribute: str = 'mobile') -> dict:
        """
            Implements authenticate and roles command for Active Directory.
        """
        referrals = []
        entries = []

        xsoar_username = self._get_ad_username(username)
        with Connection(self._ldap_server, self._username, self._password) as ldap_conn:
            attributes = [self.GROUPS_MEMBER, self.GROUPS_PRIMARY_ID]
            if pull_name:
                attributes.append(name_attribute)
            if pull_mail:
                attributes.append(mail_attribute)
            if pull_phone:
                attributes.append(phone_attribute)

            search_filter = f'(|(sAMAccountName={xsoar_username})(userPrincipalName={username}))'
            ldap_conn_entries = ldap_conn.extend.standard.paged_search(search_base=self._base_dn,
                                                                       search_filter=search_filter,
                                                                       attributes=attributes,
                                                                       paged_size=self._page_size,
                                                                       generator=False)
            if not ldap_conn_entries:
                raise Exception("LDAP Authentication - LDAP user not found")

            for entry in ldap_conn_entries:
                if entry_type := entry.get('type'):
                    if entry_type == 'searchResRef':  # a referral
                        referrals.extend(entry.get('uri'))

                    elif entry_type == 'searchResEntry':  # an entry
                        entry_dn = entry.get('dn')
                        entry_attributes = entry.get('attributes')
                        relevant_entry_attributes = []
                        for attr in entry_attributes:
                            if attr_value := entry_attributes.get(attr):
                                if not isinstance(attr_value, list):
                                    attr_value = [str(attr_value)]
                                relevant_entry_attributes.append({'Name': attr, 'Values': attr_value})

                        entries.append({'DN': entry_dn, 'Attributes': relevant_entry_attributes})
                        self.authenticate_ldap_user(entry_dn, password)

        return {
            'Controls': None,
            'Referrals': referrals,
            'Entries': entries
        }

    def authenticate_and_roles(self, username: str, password: str, pull_name: bool = True, pull_mail: bool = True,
                               pull_phone: bool = False, mail_attribute: str = 'mail', name_attribute: str = 'name',
                               phone_attribute: str = 'mobile') -> dict:
        """
            Implements authenticate and roles command.
        """
        # TODO: need to better understand what is the different between AD usernames and OpenLDAP usernames.
        #  is it possible to use DN as a username in AD?
        if self._ldap_server_type == 'Active Directory':
            return self.authenticate_and_roles_active_directory(username=username, password=password,
                                                                pull_name=pull_name, pull_mail=pull_mail,
                                                                pull_phone=pull_phone, mail_attribute=mail_attribute,
                                                                name_attribute=name_attribute,
                                                                phone_attribute=phone_attribute)
        else:  # ldap server is OpenLDAP
            return self.authenticate_and_roles_openldap(username=username, password=password,
                                                        pull_name=pull_name, pull_mail=pull_mail, pull_phone=pull_phone,
                                                        mail_attribute=mail_attribute, name_attribute=name_attribute,
                                                        phone_attribute=phone_attribute)

    def test_module(self):
        """
            Basic test connection and validation of the Ldap integration.
        """
        build_number = get_demisto_version().get('buildNumber', LdapClient.DEV_BUILD_NUMBER)
        self._get_formatted_custom_attributes()

        if build_number != LdapClient.DEV_BUILD_NUMBER \
                and LdapClient.SUPPORTED_BUILD_NUMBER > int(build_number):
            raise Exception(f'OpenLDAP integration is supported from build number: {LdapClient.SUPPORTED_BUILD_NUMBER}')

        try:
            parse_dn(self._username)
        except LDAPInvalidDnError:
            raise Exception("Invalid credentials input. Credentials must be full DN.")
        self.authenticate_ldap_user(username=self._username, password=self._password)
        demisto.results('ok')


def main():
    """ COMMANDS MANAGER / SWITCH PANEL """
    params = demisto.params()
    command = demisto.command()
    args = demisto.args()

    demisto.info(f'Command being called is {command}')
    try:
        # initialized LDAP Authentication client
        client = LdapClient(params)

        if command == 'test-module':
            client.test_module()
        elif command == 'ad-authenticate':
            username = args.get('username')
            password = args.get('password')
            authentication_result = client.authenticate_ldap_user(username, password)
            demisto.info(f'ad-authenticate command - authentication result: {authentication_result}')
            demisto.results(authentication_result)
        elif command == 'ad-groups':
            specific_group = args.get('specific-groups')
            searched_results = client.get_ldap_groups(specific_group)
            demisto.info(f'ad-groups command - searched results: {searched_results}')
            demisto.results(searched_results)
        elif command == 'ad-authenticate-and-roles':
            username = args.get('username')
            password = args.get('password')
            mail_attribute = args.get('attribute-mail', 'mail')
            name_attribute = args.get('attribute-name', 'name')
            phone_attribute = args.get('attribute-phone', 'mobile')
            pull_name = argToBoolean(args.get('attribute-name-pull', True))
            pull_mail = argToBoolean(args.get('attribute-mail-pull', True))
            pull_phone = argToBoolean(args.get('attribute-phone-pull', False))
            entry_result = client.authenticate_and_roles(username=username, password=password, pull_name=pull_name,
                                                         pull_mail=pull_mail, pull_phone=pull_phone,
                                                         mail_attribute=mail_attribute, name_attribute=name_attribute,
                                                         phone_attribute=phone_attribute)
            demisto.info(f'ad-authenticate-and-roles command - entry results: {entry_result}')
            demisto.results(entry_result)

    # Log exceptions
    except Exception as e:
        msg = str(e)
        if isinstance(e, LDAPBindError):
            msg = f'LDAP Authentication - authentication connection failed. Additional details: {msg}'
        elif isinstance(e, LDAPSocketOpenError):
            msg = f'LDAP Authentication - Failed to connect to LDAP server. Additional details: {msg}'
        elif isinstance(e, LDAPInvalidPortError):
            msg = 'LDAP Authentication - Not valid ldap server input.' \
                  ' Check that server input is of form: ip or ldap://ip'
        return_error(str(msg))


if __name__ in ['__main__', '__builtin__', 'builtins']:
    main()
