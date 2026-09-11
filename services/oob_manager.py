# services/oob_manager.py
"""Out-of-band management client: Redfish (preferred) with IPMI fallback.

Supports Dell iDRAC, HPE iLO, Huawei iBMC, Lenovo XCC and any Redfish-compliant
BMC. Credentials are decrypted via the existing Credential model.
"""
import logging
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Redfish ComputerSystem.Reset ResetType values
RESET_TYPES = {
    'power_on':       'On',
    'power_off':      'ForceOff',
    'graceful_off':   'GracefulShutdown',
    'reset':          'ForceRestart',
    'graceful_reset': 'GracefulRestart',
    'nmi':            'Nmi',
}


def _cfg(key, default):
    """Read a Flask config value, falling back when outside app context."""
    try:
        from flask import current_app
        return current_app.config.get(key, default)
    except RuntimeError:
        return default


class OobError(Exception):
    """Raised when an OOB operation fails."""


class OobManager:
    """Wraps a single BmcController and performs Redfish/IPMI operations."""

    def __init__(self, controller, credential, timeout=None, retries=None):
        self.ctrl = controller
        self.cred = credential
        self.verify = self._resolve_verify_ssl(controller)
        self.timeout = float(timeout if timeout is not None else _cfg('OOB_TIMEOUT', 10))
        self.retries = int(retries if retries is not None else 1)
        self.base = self._build_base(controller)

    def _session(self):
        s = requests.Session()
        s.verify = self.verify
        if self.cred:
            s.auth = (self.cred.username, self.cred.get_password() or '')
        return s

    @staticmethod
    def _resolve_verify_ssl(controller):
        value = getattr(controller, 'verify_ssl', None)
        if value is None:
            return bool(_cfg('OOB_VERIFY_SSL', False))
        return bool(value)

    @staticmethod
    def _build_base(controller):
        host = (getattr(controller, 'bmc_ip', None) or '').strip()
        use_ssl = getattr(controller, 'use_ssl', None)
        if use_ssl is None:
            use_ssl = True
        scheme = 'https' if use_ssl else 'http'
        port = getattr(controller, 'bmc_port', None)
        base = scheme + '://' + host
        if port not in (None, '', 0):
            port = int(port)
            if not (scheme == 'https' and port == 443) and not (scheme == 'http' and port == 80):
                base += ':%s' % port
        return base.rstrip('/')

    # ---- low-level HTTP helpers ----
    def _get(self, session, path):
        url = self.base + path
        try:
            r = session.get(url, timeout=self.timeout, headers={'Accept': 'application/json'})
        except requests.RequestException as e:
            raise OobError('connection failed: %s' % e)
        if r.status_code >= 400:
            raise OobError('HTTP %s: %s' % (r.status_code, r.text[:200]))
        try:
            return r.json()
        except ValueError:
            return {}

    def _post(self, session, path, payload):
        url = self.base + path
        try:
            r = session.post(url, json=payload, timeout=self.timeout,
                             headers={'Accept': 'application/json'})
        except requests.RequestException as e:
            raise OobError('connection failed: %s' % e)
        if r.status_code >= 400:
            raise OobError('HTTP %s: %s' % (r.status_code, r.text[:200]))
        try:
            return r.json()
        except ValueError:
            return {}

    def _patch(self, session, path, payload):
        url = self.base + path
        try:
            r = session.patch(url, json=payload, timeout=self.timeout,
                              headers={'Accept': 'application/json',
                                       'Content-Type': 'application/json',
                                       'If-Match': '*'})
        except requests.RequestException as e:
            raise OobError('connection failed: %s' % e)
        if r.status_code >= 400:
            raise OobError('HTTP %s: %s' % (r.status_code, r.text[:300]))
        try:
            return r.json()
        except ValueError:
            return {}

    # ---- system info ----
    def get_system(self):
        """Return the first Redfish ComputerSystem resource (as a dict)."""
        session = self._session()
        root = self._get(session, '/redfish/v1/')
        systems_odata = (root.get('Systems') or {}).get('@odata.id')
        if not systems_odata:
            raise OobError('no Systems collection in Redfish root')
        systems = self._get(session, systems_odata)
        members = systems.get('Members') or []
        if not members:
            raise OobError('no ComputerSystem members')
        return self._get(session, members[0]['@odata.id'])

    def get_power_state(self):
        system = self.get_system()
        return system.get('PowerState')

    # ---- Redfish probe / BMC auto-discovery ----
    def probe(self):
        """Lightweight Redfish probe used for BMC auto-discovery.

        Returns enough normalized inventory to create or enrich a BmcController
        without doing a full sensor/event poll. Any failed sub-resource read is
        downgraded to an empty value instead of aborting the probe.
        """
        session = self._session()
        root = self._get(session, '/redfish/v1/')

        manager = {}
        managers_odata = (root.get('Managers') or {}).get('@odata.id')
        if managers_odata:
            try:
                managers = self._get(session, managers_odata)
                members = managers.get('Members') or []
                if members:
                    manager = self._get(session, members[0]['@odata.id'])
            except OobError as exc:
                logger.debug('Redfish manager probe failed for %s: %s',
                             self.ctrl.bmc_ip, exc)

        system = {}
        try:
            system = self.get_system()
        except OobError as exc:
            logger.debug('Redfish system probe failed for %s: %s',
                         self.ctrl.bmc_ip, exc)

        firmware_version = (manager.get('FirmwareVersion')
                            or system.get('BiosVersion')
                            or manager.get('BiosVersion'))
        vendor = self._infer_vendor(root, system, manager)
        return {
            'reachable': True,
            'protocol': 'redfish',
            'redfish_version': root.get('RedfishVersion') or '',
            'vendor': vendor or system.get('Manufacturer') or manager.get('Manufacturer'),
            'manufacturer': system.get('Manufacturer') or manager.get('Manufacturer') or '',
            'model': system.get('Model') or manager.get('Model') or '',
            'serial_number': system.get('SerialNumber') or manager.get('SerialNumber') or '',
            'firmware_version': firmware_version or '',
            'bios_version': system.get('BiosVersion') or '',
            'power_state': system.get('PowerState') or '',
            'asset_tag': system.get('AssetTag') or '',
            'hostname': system.get('HostName') or manager.get('HostName') or '',
        }

    def test_connection(self):
        """Probe connectivity/auth and return a compact result for the UI."""
        started = time.perf_counter()
        info = self.probe()
        info['latency_ms'] = round((time.perf_counter() - started) * 1000, 1)
        info['base_url'] = self.base
        info['verify_ssl'] = self.verify
        return info

    @staticmethod
    def _infer_vendor(root, system, manager):
        """Infer a normalized vendor from Redfish resource names/OEM markers."""
        blob = ' '.join([
            str(root.get('Name') or ''),
            str(manager.get('Name') or ''),
            str(manager.get('Manufacturer') or ''),
            str(system.get('Manufacturer') or ''),
            str(manager.get('Oem') or ''),
            str(root.get('Oem') or ''),
        ]).lower()
        if any(k in blob for k in ('idrac', 'dell', 'openmanage')):
            return 'dell'
        if any(k in blob for k in ('ilo', 'hpe', 'hewlett packard')):
            return 'hpe'
        if any(k in blob for k in ('ibmc', 'huawei')):
            return 'huawei'
        if any(k in blob for k in ('xcc', 'lenovo')):
            return 'lenovo'
        if any(k in blob for k in ('inspur', 'tsinghua', 'unigroup')):
            return 'inspur'
        return ''

    # ---- power action ----
    def power_action(self, action):
        if action not in RESET_TYPES:
            raise OobError('unknown action: %s' % action)
        reset_type = RESET_TYPES[action]
        session = self._session()
        system = self.get_system()
        actions = system.get('Actions') or {}
        reset = actions.get('#ComputerSystem.Reset') or {}
        target = reset.get('target')
        if not target:
            target = (system.get('@odata.id') or '/redfish/v1/Systems/1') + '/Actions/ComputerSystem.Reset'
        self._post(session, target, {'ResetType': reset_type})
        return {'action': action, 'reset_type': reset_type, 'target': target}

    # ---- sensors ----
    def get_sensors(self):
        """Return a normalized list of sensor dicts (temperature / fan / voltage / power)."""
        sensors = []
        session = self._session()
        try:
            root = self._get(session, '/redfish/v1/')
            chassis_odata = (root.get('Chassis') or {}).get('@odata.id')
            if not chassis_odata:
                return sensors
            chassis = self._get(session, chassis_odata)
            for m in chassis.get('Members') or []:
                c = self._get(session, m['@odata.id'])
                thermal = c.get('Thermal') or {}
                for t in thermal.get('Temperatures') or []:
                    sensors.append(self._norm_sensor(t, 'temperature'))
                for f in thermal.get('Fans') or []:
                    sensors.append(self._norm_sensor(f, 'fan'))
                for v in thermal.get('Voltages') or []:
                    sensors.append(self._norm_sensor(v, 'voltage'))
                power = c.get('Power') or {}
                for p in power.get('PowerControl') or []:
                    sensors.append({
                        'name': p.get('Name') or 'Power',
                        'kind': 'power',
                        'reading': p.get('PowerConsumedWatts'),
                        'unit': 'W',
                        'status': _redfish_health(p.get('Status')),
                        'lower_warning': None,
                        'upper_warning': None,
                        'lower_critical': None,
                        'upper_critical': (p.get('PowerLimit') or {}).get('LimitInWatts'),
                    })
        except OobError as e:
            logger.warning('Redfish sensor read failed for %s: %s', self.ctrl.bmc_ip, e)
        return sensors

    @staticmethod
    def _norm_sensor(item, kind):
        return {
            'name': item.get('Name'),
            'kind': kind,
            'reading': item.get('ReadingCelsius') if kind == 'temperature' else item.get('Reading'),
            'unit': 'C' if kind == 'temperature' else (item.get('ReadingUnits') or ''),
            'status': _redfish_health(item.get('Status')),
            'lower_warning': item.get('LowerThresholdNonCritical'),
            'upper_warning': item.get('UpperThresholdNonCritical'),
            'lower_critical': item.get('LowerThresholdCritical'),
            'upper_critical': item.get('UpperThresholdCritical'),
        }

    # ---- network interfaces (iDRAC NIC inventory) ----
    def get_network(self):
        """Return the list of host NICs with MAC/addresses (best effort)."""
        out = []
        session = self._session()
        try:
            root = self._get(session, '/redfish/v1/')
            systems_odata = (root.get('Systems') or {}).get('@odata.id')
            if not systems_odata:
                return out
            systems = self._get(session, systems_odata)
            members = systems.get('Members') or []
            if not members:
                return out
            system = self._get(session, members[0]['@odata.id'])
            eth = system.get('EthernetInterfaces') or {}
            eth_url = eth.get('@odata.id')
            if not eth_url:
                return out
            col = self._get(session, eth_url)
            for m in col.get('Members') or []:
                itf = self._get(session, m['@odata.id'])
                out.append({
                    'name': itf.get('Name'),
                    'description': itf.get('Description'),
                    'mac': itf.get('MACAddress'),
                    'speed': itf.get('SpeedMbps'),
                    'status': _redfish_health(itf.get('Status')),
                    'enabled': itf.get('InterfaceEnabled'),
                    'vlan': (itf.get('VLANs') or {}).get('VLANEnable'),
                })
        except OobError as e:
            logger.warning('Redfish network read failed for %s: %s',
                           self.ctrl.bmc_ip, e)
        return out

    # ---- overall health (Systems + Chassis) ----
    def get_health(self):
        """Return aggregated health + rolling power consumption."""
        health = {'rollup': 'unknown', 'power_watts': None, 'details': []}
        session = self._session()
        try:
            root = self._get(session, '/redfish/v1/')
            systems_odata = (root.get('Systems') or {}).get('@odata.id')
            chassis_odata = (root.get('Chassis') or {}).get('@odata.id')
            if systems_odata:
                systems = self._get(session, systems_odata)
                for m in systems.get('Members') or []:
                    s = self._get(session, m['@odata.id'])
                    health['details'].append({
                        'type': 'system', 'name': s.get('Name'),
                        'health': _redfish_health(s.get('Status')),
                        'power': (s.get('PowerState') or ''),
                    })
            if chassis_odata:
                chassis = self._get(session, chassis_odata)
                for m in chassis.get('Members') or []:
                    c = self._get(session, m['@odata.id'])
                    health['details'].append({
                        'type': 'chassis', 'name': c.get('Name'),
                        'health': _redfish_health(c.get('Status')),
                    })
                    power = c.get('Power') or {}
                    for p in power.get('PowerControl') or []:
                        watts = p.get('PowerConsumedWatts')
                        if watts is not None:
                            health['power_watts'] = watts
        except OobError as e:
            logger.warning('Redfish health read failed for %s: %s',
                           self.ctrl.bmc_ip, e)
        if health['details']:
            sts = {d['health'] for d in health['details']}
            if 'critical' in sts:
                health['rollup'] = 'critical'
            elif 'warning' in sts:
                health['rollup'] = 'warning'
            elif sts and sts <= {'ok'}:
                health['rollup'] = 'ok'
        return health

    # ---- BIOS attributes (iDRAC /redfish/v1/Systems/<id>/Bios) ----
    def get_bios_attributes(self):
        """Return current + pending BIOS attribute dictionaries."""
        attrs, pending = {}, {}
        session = self._session()
        try:
            system = self.get_system()
            sys_id = system.get('@odata.id') or '/redfish/v1/Systems/1'
            bios = self._get(session, sys_id + '/Bios')
            attrs = bios.get('Attributes') or {}
        except OobError as e:
            logger.warning('Redfish BIOS read failed for %s: %s',
                           self.ctrl.bmc_ip, e)
        try:
            system = self.get_system()
            sys_id = system.get('@odata.id') or '/redfish/v1/Systems/1'
            settings = self._get(session, sys_id + '/Bios/Settings')
            pending = settings.get('Attributes') or {}
        except OobError as e:
            logger.warning('Redfish BIOS settings read failed for %s: %s',
                           self.ctrl.bmc_ip, e)
        return {'attributes': attrs, 'pending': pending}

    def set_bios_attributes(self, attrs):
        """PATCH BIOS attributes (best-effort). Returns applied/failed lists."""
        result = {'applied': [], 'failed': [], 'skipped': []}
        if not attrs:
            result['skipped'].append('empty attribute set')
            return result
        try:
            system = self.get_system()
        except OobError as e:
            result['failed'].append('system read: %s' % e)
            return result
        sys_id = system.get('@odata.id') or '/redfish/v1/Systems/1'
        session = self._session()
        try:
            self._patch(session, sys_id + '/Bios/Settings',
                        {'Attributes': attrs})
            result['applied'] = list(attrs.keys())
        except OobError as e:
            result['failed'].append(str(e))
        return result

    # ---- firmware inventory + upgrade (对标 DCOS「固件升级」) ----
    def get_firmware_inventory(self):
        """Return firmware + software inventory entries (Redfish UpdateService)."""
        items = []
        session = self._session()
        try:
            root = self._get(session, '/redfish/v1/')
            us = (root.get('UpdateService') or {}).get('@odata.id')
            if not us:
                return items
            svc = self._get(session, us)
            for key in ('FirmwareInventory', 'SoftwareInventory'):
                col_url = (svc.get(key) or {}).get('@odata.id')
                if not col_url:
                    continue
                col = self._get(session, col_url)
                for m in (col.get('Members') or []):
                    it = self._get(session, m['@odata.id'])
                    items.append({
                        'name': it.get('Name') or it.get('Id'),
                        'id': it.get('Id'),
                        'version': it.get('Version'),
                        'software_id': it.get('SoftwareId'),
                        'release_date': (it.get('ReleaseDate') or '')[:10],
                        'state': it.get('Status', {}).get('State') if isinstance(it.get('Status'), dict) else it.get('Status'),
                        'kind': 'firmware' if key == 'FirmwareInventory' else 'software',
                        'updateable': bool(it.get('Updateable', False)),
                    })
        except OobError as e:
            logger.warning('Redfish firmware inventory read failed for %s: %s',
                           self.ctrl.bmc_ip, e)
        return items

    def get_update_service(self):
        """Return UpdateService capabilities + SimpleUpdate target if present."""
        session = self._session()
        try:
            root = self._get(session, '/redfish/v1/')
            us = (root.get('UpdateService') or {}).get('@odata.id')
            if not us:
                return {'available': False, 'simple_update': None,
                        'http_push_uri': None, 'targets': []}
            svc = self._get(session, us)
            actions = svc.get('Actions') or {}
            su = actions.get('#UpdateService.SimpleUpdate') or {}
            target = su.get('target') or svc.get('SimpleUpdate',
                                                 {}).get('target')
            return {
                'available': True,
                'simple_update': target,
                'http_push_uri': svc.get('HttpPushUri'),
                'service_enabled': svc.get('ServiceEnabled'),
                'targets': [(t.get('@odata.id') or t.get('Id'))
                            for t in (svc.get('Targets') or [])],
                'status': _redfish_health(svc.get('Status')),
            }
        except OobError as e:
            logger.warning('Redfish UpdateService read failed for %s: %s',
                           self.ctrl.bmc_ip, e)
            return {'available': False, 'error': str(e)}

    def update_firmware(self, image_url, targets=None, transfer_protocol='HTTP'):
        """Trigger a firmware upgrade via Redfish SimpleUpdate.

        Returns {'task': <task_url_or_dict>, 'raw': {...}} or raises OobError.
        Most vendors return a Task resource to poll for progress.
        """
        session = self._session()
        root = self._get(session, '/redfish/v1/')
        us = (root.get('UpdateService') or {}).get('@odata.id')
        if not us:
            raise OobError('no UpdateService in Redfish root')
        svc = self._get(session, us)
        actions = svc.get('Actions') or {}
        su = actions.get('#UpdateService.SimpleUpdate') or {}
        target = su.get('target') or svc.get('SimpleUpdate', {}).get('target')
        if not target:
            raise OobError('UpdateService.SimpleUpdate target not found')
        payload = {'ImageURI': image_url,
                   'TransferProtocol': transfer_protocol}
        if targets:
            payload['Targets'] = targets
        raw = self._post(session, target, payload)
        task = None
        if isinstance(raw, dict):
            task = raw.get('@odata.id') or raw.get('TaskMonitor') or raw.get('Id')
        return {'task': task, 'raw': raw}

    def get_task_status(self, task_ref):
        """Poll a Redfish Task resource for state/status/progress.

        task_ref is the URI captured when the firmware job was submitted
        (Redfish Task @odata.id, possibly absolute or relative). Returns a
        normalized dict; callers map 'completed'/'failed' onto job lifecycle.
        """
        out = {'state': None, 'status': None, 'percent': None,
               'message': None, 'completed': False, 'failed': False}
        if not task_ref:
            return out
        session = self._session()
        url = task_ref if str(task_ref).startswith(('http://', 'https://')) \
            else self.base + task_ref
        try:
            r = session.get(url, timeout=self.timeout,
                            headers={'Accept': 'application/json'})
        except requests.RequestException as e:
            raise OobError('task poll connection failed: %s' % e)
        if r.status_code >= 400:
            raise OobError('task poll HTTP %s: %s' % (r.status_code, r.text[:200]))
        try:
            data = r.json()
        except ValueError:
            return out
        state = str(data.get('TaskState') or data.get('JobStatus') or '').lower()
        out['state'] = state
        out['status'] = str(data.get('TaskStatus') or '').lower()
        percent = data.get('PercentComplete')
        if percent is not None:
            out['percent'] = percent
        msgs = data.get('Messages') or []
        if isinstance(msgs, list):
            out['message'] = '; '.join(
                m.get('Message', '') for m in msgs
                if isinstance(m, dict) and m.get('Message'))
        out['completed'] = state in ('completed', 'complete')
        out['failed'] = state in ('exception', 'failed', 'killed',
                                  'cancelled', 'cancelling', 'interrupted')
        return out

    # ---- config snapshot / restore (对标 DCOS「服务器备份」) ----
    def get_config_snapshot(self):
        """Collect a portable config snapshot: system info + BIOS attributes + NICs.

        Returns a dict; on Redfish failure returns an empty dict so callers can
        detect and surface the error.
        """
        snap = {'bmc_ip': self.ctrl.bmc_ip, 'system': {}, 'bios_attributes': {}}
        try:
            system = self.get_system()
        except OobError as e:
            logger.warning('OOB snapshot system read failed %s: %s',
                           self.ctrl.bmc_ip, e)
            return snap
        keep = ('Name', 'Model', 'Manufacturer', 'SerialNumber', 'PowerState',
                'BiosVersion', 'SKU', 'AssetTag', 'HostName', 'PartNumber',
                'UUID', 'Status')
        snap['system'] = {k: system.get(k) for k in keep if k in system}
        sys_id = system.get('@odata.id') or '/redfish/v1/Systems/1'
        session = self._session()
        try:
            bios = self._get(session, sys_id + '/Bios')
            snap['bios_attributes'] = bios.get('Attributes') or {}
        except OobError as e:
            logger.warning('OOB snapshot BIOS read failed %s: %s',
                           self.ctrl.bmc_ip, e)
        try:
            snap['network'] = self.get_network()
        except OobError as e:
            logger.warning('OOB snapshot NIC read failed %s: %s',
                           self.ctrl.bmc_ip, e)
            snap['network'] = []
        return snap

    def restore_config(self, snapshot):
        """Best-effort restore of BIOS attributes via Redfish PATCH.

        Returns {'applied': [...], 'failed': [...], 'skipped': [...]} so the
        caller can report exactly what happened (some attributes are read-only).
        """
        result = {'applied': [], 'failed': [], 'skipped': []}
        attrs = (snapshot or {}).get('bios_attributes') or {}
        if not attrs:
            result['skipped'].append('no bios_attributes in snapshot')
            return result
        try:
            system = self.get_system()
        except OobError as e:
            result['failed'].append('system read: %s' % e)
            return result
        sys_id = system.get('@odata.id') or '/redfish/v1/Systems/1'
        session = self._session()
        try:
            self._patch(session, sys_id + '/Bios/Settings',
                        {'Attributes': attrs})
            result['applied'] = list(attrs.keys())
        except OobError as e:
            # Redfish often rejects the whole patch if any single attribute is
            # read-only; report the failure and let the operator inspect.
            result['failed'].append(str(e))
        return result

    # ---- event logs (iDRAC LogServices: SEL / Lifecycle) ----
    def get_logs(self, log_type='sel', max_entries=100):
        """Return recent entries from a LogService (default SEL)."""
        entries = []
        session = self._session()
        try:
            system = self.get_system()
            sys_id = system.get('@odata.id') or '/redfish/v1/Systems/1'
            col = self._get(session, sys_id + '/LogServices')
            for m in col.get('Members') or []:
                svc = self._get(session, m['@odata.id'])
                name = (svc.get('Name') or '').lower()
                if log_type and log_type.lower() not in name:
                    continue
                entries_url = (svc.get('Entries') or {}).get('@odata.id')
                if not entries_url:
                    continue
                ent_col = self._get(session, entries_url)
                for e in (ent_col.get('Members') or [])[:max_entries]:
                    entry = self._get(session, e['@odata.id'])
                    entries.append({
                        'entry_type': entry.get('EntryType'),
                        'severity': entry.get('Severity'),
                        'message': entry.get('Message'),
                        'message_id': entry.get('MessageId'),
                        'created': entry.get('Created'),
                        'sensor_type': entry.get('SensorType'),
                        'event_id': entry.get('EventId'),
                    })
                break
        except OobError as e:
            logger.warning('Redfish log read failed for %s: %s',
                           self.ctrl.bmc_ip, e)
        return entries

    # ---- IPMI fallback ----
    def get_system_ipmi(self):
        """Fallback to IPMI (requires pyghmi) when Redfish is unavailable."""
        try:
            from pyghmi.ipmi import command
        except ImportError:
            raise OobError('pyghmi not installed and Redfish unavailable')
        try:
            ipmi = command.Command(
                bmc=self.ctrl.bmc_ip,
                userid=self.cred.username,
                password=self.cred.get_password() or '',
            )
            power = ipmi.get_power() or {}
            return {
                'PowerState': 'On' if power.get('powerstate') == 'on' else 'Off',
                'Model': '',
                'SerialNumber': '',
                'BiosVersion': '',
            }
        except Exception as e:
            raise OobError('IPMI failed: %s' % e)


def _redfish_health(status):
    st = (status or {}).get('Health') or 'OK'
    st = st.lower()
    if st in ('ok', 'good'):
        return 'ok'
    if st in ('warning', 'caution'):
        return 'warning'
    return 'critical'