#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2017 F5 Networks Inc.
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

ANSIBLE_METADATA = {
    'status': ['preview'],
    'supported_by': 'community',
    'metadata_version': '1.0'
}

DOCUMENTATION = '''
---
module: bigip_monitor_tcp
short_description: Manages F5 BIG-IP LTM tcp monitors.
description: Manages F5 BIG-IP LTM tcp monitors via iControl SOAP API.
version_added: "1.4"
options:
  name:
    description:
      - Monitor name.
    required: True
    aliases:
      - monitor
  parent:
    description:
      - The parent template of this monitor template. Once this value has
        been set, it cannot be changed. By default, this value is the C(tcp)
        parent on the C(Common) partition.
    default: "/Common/tcp"
  send:
    description:
      - The send string for the monitor call.
  receive:
    description:
      - The receive string for the monitor call.
  ip:
    description:
      - IP address part of the IP/port definition. If this parameter is not
        provided when creating a new monitor, then the default value will be
        '*'.
      - If this value is an IP address, and the C(type) is C(tcp) (the default),
        then a C(port) number must be specified.
  type:
    description:
      - The template type of this monitor template.
      - Deprecated in 2.4. Use one of the C(bigip_monitor_tcp_echo) or
        C(bigip_monitor_tcp_half_open) modules instead.
    default: 'tcp'
    choices:
      - tcp
      - tcp_echo
      - tcp_half_open
      - TTYPE_TCP
      - TTYPE_TCP_ECHO
      - TTYPE_TCP_HALF_OPEN
  port:
    description:
      - Port address part of the IP/port definition. If this parameter is not
        provided when creating a new monitor, then the default value will be
        '*'. Note that if specifying an IP address, a value between 1 and 65535
        must be specified
      - This argument is not supported for TCP Echo types.
  interval:
    description:
      - The interval specifying how frequently the monitor instance of this
        template will run. If this parameter is not provided when creating
        a new monitor, then the default value will be 5. This value B(must)
        be less than the C(timeout) value.
  timeout:
    description:
      - The number of seconds in which the node or service must respond to
        the monitor request. If the target responds within the set time
        period, it is considered up. If the target does not respond within
        the set time period, it is considered down. You can change this
        number to any number you want, however, it should be 3 times the
        interval number of seconds plus 1 second. If this parameter is not
        provided when creating a new monitor, then the default value will be 16.
  time_until_up:
    description:
      - Specifies the amount of time in seconds after the first successful
        response before a node will be marked up. A value of 0 will cause a
        node to be marked up immediately after a valid response is received
        from the node. If this parameter is not provided when creating
        a new monitor, then the default value will be 0.
notes:
  - Requires the f5-sdk Python package on the host. This is as easy as pip
    install f5-sdk.
  - Requires BIG-IP software version >= 12
requirements:
  - f5-sdk >= 2.2.3
extends_documentation_fragment: f5
author:
  - Tim Rupp (@caphrim007)
'''

EXAMPLES = '''
- name: Create TCP Monitor
  bigip_monitor_tcp:
      state: "present"
      server: "lb.mydomain.com"
      user: "admin"
      password: "secret"
      name: "my_tcp_monitor"
      type: "tcp"
      send: "tcp string to send"
      receive: "tcp string to receive"
  delegate_to: localhost

- name: Remove TCP Monitor
  bigip_monitor_tcp:
      state: "absent"
      server: "lb.mydomain.com"
      user: "admin"
      password: "secret"
      name: "my_tcp_monitor"
  delegate_to: localhost
'''

RETURN = '''
parent:
    description: New parent template of the monitor.
    returned: changed
    type: string
    sample: "tcp"
send:
    description: The new send string for this monitor.
    returned: changed
    type: string
    sample: "tcp string to send"
receive:
    description: The new receive string for this monitor.
    returned: changed
    type: string
    sample: "tcp string to receive"
ip:
    description: The new IP of IP/port definition.
    returned: changed
    type: string
    sample: "10.12.13.14"
port:
    description: The new port of IP/port definition.
    returned: changed
    type: string
    sample: "admin@root.local"
interval:
    description: The new interval in which to run the monitor check.
    returned: changed
    type: int
    sample: 2
timeout:
    description: The new timeout in which the remote system must respond to the monitor.
    returned: changed
    type: int
    sample: 10
time_until_up:
    description: The new time in which to mark a system as up after first successful response.
    returned: changed
    type: int
    sample: 2
'''

import netaddr
import os

from ansible.module_utils.f5_utils import (
    AnsibleF5Client,
    AnsibleF5Parameters,
    HAS_F5SDK,
    F5ModuleError,
    iControlUnexpectedHTTPError,
    iteritems,
    defaultdict
)


class Parameters(AnsibleF5Parameters):
    api_map = {
        'timeUntilUp': 'time_until_up',
        'defaultsFrom': 'parent',
        'recv': 'receive'
    }

    api_attributes = [
        'timeUntilUp', 'defaultsFrom', 'interval', 'timeout', 'recv', 'send',
        'destination'
    ]

    returnables = [
        'parent', 'send', 'receive', 'ip', 'port', 'interval', 'timeout',
        'time_until_up'
    ]

    updatables = [
        'destination', 'send', 'receive', 'interval', 'timeout', 'time_until_up'
    ]

    def __init__(self, params=None):
        self._values = defaultdict(lambda: None)
        if params:
            self.update(params=params)

    def update(self, params=None):
        if params:
            for k, v in iteritems(params):
                if self.api_map is not None and k in self.api_map:
                    map_key = self.api_map[k]
                else:
                    map_key = k

                # Handle weird API parameters like `dns.proxy.__iter__` by
                # using a map provided by the module developer
                class_attr = getattr(type(self), map_key, None)
                if isinstance(class_attr, property):
                    # There is a mapped value for the api_map key
                    if class_attr.fset is None:
                        # If the mapped value does not have
                        # an associated setter
                        self._values[map_key] = v
                    else:
                        # The mapped value has a setter
                        setattr(self, map_key, v)
                else:
                    # If the mapped value is not a @property
                    self._values[map_key] = v

    def _get_default_parent_type(self):
        return '/Common/tcp'

    def _validate_port_option_with_ip(self):
        if self.port in [None, '*']:
            raise F5ModuleError(
                "Specifying an IP address requires that a port number be specified"
            )

    def __init__(self, params=None):
        super(Parameters, self).__init__(params)
        self._values['__warnings'] = []

    def to_return(self):
        result = {}
        try:
            for returnable in self.returnables:
                result[returnable] = getattr(self, returnable)
            result = self._filter_params(result)
            return result
        except Exception:
            return result

    def api_params(self):
        result = {}
        for api_attribute in self.api_attributes:
            if self.api_map is not None and api_attribute in self.api_map:
                result[api_attribute] = getattr(self, self.api_map[api_attribute])
            else:
                result[api_attribute] = getattr(self, api_attribute)
        result = self._filter_params(result)
        return result

    @property
    def destination(self):
        result = '{0}:{1}'.format(self.ip, self.port)
        return result

    @destination.setter
    def destination(self, value):
        ip, port = value.split(':')
        self._values['ip'] = ip
        self._values['port'] = port

    @property
    def interval(self):
        if self._values['interval'] is None:
            return None

        # Per BZ617284, the BIG-IP UI does not raise a warning about this.
        # So i
        if 1 > self._values['interval'] > 86400:
            raise F5ModuleError(
                "Interval value must be between 1 and 86400"
            )
        return int(self._values['interval'])

    @property
    def timeout(self):
        if self._values['timeout'] is None:
            return None
        return int(self._values['timeout'])

    @property
    def ip(self):
        if self._values['ip'] is None:
            if self._values['state'] == 'present':
                return '*'
            return None
        try:
            if self._values['ip'] in ['*', '0.0.0.0']:
                return '*'
            result = str(netaddr.IPAddress(self._values['ip']))
            self._validate_port_option_with_ip()
            return result
        except netaddr.core.AddrFormatError:
            raise F5ModuleError(
                "The provided 'ip' parameter is not an IP address."
            )

    @property
    def port(self):
        if self.type == 'tcp_echo':
            return None

        if self._values['port'] is None:
            if self._values['state'] == 'present':
                return '*'
            return None
        elif self._values['port'] == '*':
            return '*'
        return int(self._values['port'])

    @property
    def time_until_up(self):
        if self._values['time_until_up'] is None:
            if self._values['state'] == 'present':
                return 0
            return None
        return int(self._values['time_until_up'])

    @property
    def parent(self):
        if self._values['parent'] is None:
            if self._values['state'] == 'present':
                return self._get_default_parent_type()
            return None

        # TODO: Remove in 2.5. Instead just return the _values['parent'] value.
        if self._values['parent'].startswith('/'):
            parent = os.bar.basename(self._values['parent'])
            result = '/{0}/{1}'.format(self.partition, parent)
        else:
            result = '/{0}/{1}'.format(self.partition, self._values['parent'])
        return result

    @property
    def parent_partition(self):
        if self._values['parent_partition'] is None:
            return None
        self._values['__warnings'].append(
            dict(
                msg="The parent_partition param is deprecated",
                version='2.4'
            )
        )
        return self._values['parent_partition']

    @property
    def type(self):
        self._values['__warnings'].append(
            dict(
                msg="The type param is deprecated",
                version='2.4'
            )
        )
        # TODO: Remove in 2.5
        if self._values['type'] in [None, 'tcp', 'TTYPE_TCP']:
            return 'tcp'
        elif self._values['type'] in ['TTYPE_TCP_ECHO']:
            return 'tcp_echo'
        elif self._values['type'] in ['TTYPE_TCP_HALF_OPEN']:
            return 'tcp_half_open'

    @type.setter
    def type(self, value):
        self._values['type'] = value


class ParametersEcho(Parameters):
    api_map = {
        'timeUntilUp': 'time_until_up',
        'defaultsFrom': 'parent'
    }

    api_attributes = [
        'timeUntilUp', 'defaultsFrom', 'interval', 'timeout', 'destination'
    ]

    returnables = [
        'parent', 'ip', 'interval', 'timeout', 'time_until_up'
    ]

    updatables = [
        'destination', 'interval', 'timeout', 'time_until_up'
    ]

    def _get_default_parent_type(self):
        return '/Common/tcp_echo'

    def _validate_port_option_with_ip(self):
        pass

    @property
    def destination(self):
        return self.ip

    @destination.setter
    def destination(self, value):
        self._values['ip'] = value

    @property
    def send(self):
        if self._values['send'] is None:
            return None
        raise F5ModuleError(
            "The 'send' parameter is not available for TCP echo"
        )

    @property
    def receive(self):
        if self._values['receive'] is None:
            return None
        raise F5ModuleError(
            "The 'receive' parameter is not available for TCP echo"
        )

    @property
    def port(self):
        if self._values['port'] is None:
            return None
        raise F5ModuleError(
            "The 'port' parameter is not available for TCP echo"
        )


class ParametersHalfOpen(Parameters):
    api_map = {
        'timeUntilUp': 'time_until_up',
        'defaultsFrom': 'parent'
    }

    api_attributes = [
        'timeUntilUp', 'defaultsFrom', 'interval', 'timeout', 'destination'
    ]

    returnables = [
        'parent', 'ip', 'port', 'interval', 'timeout', 'time_until_up'
    ]

    updatables = [
        'destination', 'interval', 'timeout', 'time_until_up'
    ]

    def _get_default_parent_type(self):
        return '/Common/tcp_half_open'

    @property
    def send(self):
        if self._values['send'] is None:
            return None
        raise F5ModuleError(
            "The 'send' parameter is not available for TCP half open"
        )

    @property
    def receive(self):
        if self._values['receive'] is None:
            return None
        raise F5ModuleError(
            "The 'receive' parameter is not available for TCP half open"
        )


class Difference(object):
    def __init__(self, want, have=None):
        self.want = want
        self.have = have

    def compare(self, param):
        try:
            result = getattr(self, param)
            return result
        except AttributeError:
            result = self.__default(param)
            return result

    @property
    def parent(self):
        if self.want.parent != self.want.parent:
            raise F5ModuleError(
                "The parent monitor cannot be changed"
            )

    @property
    def interval(self):
        if self.have.timeout:
            # Update
            if self.want.timeout:
                if self.want.interval >= self.want.timeout:
                    raise F5ModuleError(
                        "Parameter 'interval' must be less than 'timeout'."
                    )
            if self.want.interval >= self.have.timeout:
                raise F5ModuleError(
                    "Parameter 'interval' must be less than 'timeout'."
                )
        else:
            if self.want.timeout:
                if self.want.interval >= self.want.timeout:
                    raise F5ModuleError(
                        "Parameter 'interval' must be less than 'timeout'."
                    )
        if self.want.interval != self.have.interval:
            return self.want.interval

    def __default(self, param):
        attr1 = getattr(self.want, param)
        try:
            attr2 = getattr(self.have, param)
            if attr1 != attr2:
                return attr1
        except AttributeError:
            return attr1


# TODO: Remove all of this in 2.5
class ModuleManager(object):
    def __init__(self, client):
        self.client = client

    def exec_module(self):
        type = self.client.module.params.get('type', 'tcp')
        manager = self.get_manager(type)
        return manager.exec_module()

    def get_manager(self, type):
        if type in ['tcp', 'TTYPE_TCP']:
            return TcpManager(self.client)
        elif type in ['tcp_echo', 'TTYPE_TCP_ECHO']:
            return TcpEchoManager(self.client)
        elif type in ['tcp_half_open', 'TTYPE_TCP_HALF_OPEN']:
            return TcpHalfOpenManager(self.client)


class BaseManager(object):
    def _announce_deprecations(self):
        warnings = []
        if self.want:
            warnings += self.want._values.get('__warnings', [])
        if self.have:
            warnings += self.have._values.get('__warnings', [])
        for warning in warnings:
            self.client.module.deprecate(
                msg=warning['msg'],
                version=warning['version']
            )

    def exec_module(self):
        changed = False
        result = dict()
        state = self.want.state

        try:
            if state == "present":
                changed = self.present()
            elif state == "absent":
                changed = self.absent()
        except iControlUnexpectedHTTPError as e:
            raise F5ModuleError(str(e))

        changes = self.changes.to_return()
        result.update(**changes)
        result.update(dict(changed=changed))
        self._announce_deprecations()
        return result

    def present(self):
        if self.exists():
            return self.update()
        else:
            return self.create()

    def create(self):
        self._set_changed_options()
        if self.want.timeout is None:
            self.want.update({'timeout': 16})
        if self.want.interval is None:
            self.want.update({'interval': 5})
        if self.client.check_mode:
            return True
        self.create_on_device()
        return True

    def should_update(self):
        result = self._update_changed_options()
        if result:
            return True
        return False

    def update(self):
        self.have = self.read_current_from_device()
        if not self.should_update():
            return False
        if self.client.check_mode:
            return True
        self.update_on_device()
        return True

    def absent(self):
        if self.exists():
            return self.remove()
        return False

    def remove(self):
        if self.client.check_mode:
            return True
        self.remove_from_device()
        if self.exists():
            raise F5ModuleError("Failed to delete the monitor.")
        return True


class TcpManager(BaseManager):
    def __init__(self, client):
        self.client = client
        self.have = None
        self.want = Parameters(self.client.module.params)
        self.changes = Parameters()

    def _set_changed_options(self):
        changed = {}
        for key in Parameters.returnables:
            if getattr(self.want, key) is not None:
                changed[key] = getattr(self.want, key)
        if changed:
            self.changes = Parameters(changed)

    def _update_changed_options(self):
        diff = Difference(self.want, self.have)
        updatables = Parameters.updatables
        changed = dict()
        for k in updatables:
            change = diff.compare(k)
            if change is None:
                continue
            else:
                changed[k] = change
        if changed:
            self.changes = Parameters(changed)
            return True
        return False

    def read_current_from_device(self):
        resource = self.client.api.tm.ltm.monitor.tcps.tcp.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result = resource.attrs
        return Parameters(result)

    def exists(self):
        result = self.client.api.tm.ltm.monitor.tcps.tcp.exists(
            name=self.want.name,
            partition=self.want.partition
        )
        return result

    def update_on_device(self):
        params = self.want.api_params()
        result = self.client.api.tm.ltm.monitor.tcps.tcp.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result.modify(**params)

    def create_on_device(self):
        params = self.want.api_params()
        self.client.api.tm.ltm.monitor.tcps.tcp.create(
            name=self.want.name,
            partition=self.want.partition,
            **params
        )

    def remove_from_device(self):
        result = self.client.api.tm.ltm.monitor.tcps.tcp.load(
            name=self.want.name,
            partition=self.want.partition
        )
        if result:
            result.delete()


# TODO: Remove this in 2.5 and put it its own module
class TcpEchoManager(BaseManager):
    def __init__(self, client):
        self.client = client
        self.have = None
        self.want = ParametersEcho(self.client.module.params)
        self.changes = ParametersEcho()

    def _set_changed_options(self):
        changed = {}
        for key in ParametersEcho.returnables:
            if getattr(self.want, key) is not None:
                changed[key] = getattr(self.want, key)
        if changed:
            self.changes = ParametersEcho(changed)

    def _update_changed_options(self):
        diff = Difference(self.want, self.have)
        updatables = ParametersEcho.updatables
        changed = dict()
        for k in updatables:
            change = diff.compare(k)
            if change is None:
                continue
            else:
                changed[k] = change
        if changed:
            self.changes = ParametersEcho(changed)
            return True
        return False

    def read_current_from_device(self):
        resource = self.client.api.tm.ltm.monitor.tcp_echos.tcp_echo.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result = resource.attrs
        return ParametersEcho(result)

    def exists(self):
        result = self.client.api.tm.ltm.monitor.tcp_echos.tcp_echo.exists(
            name=self.want.name,
            partition=self.want.partition
        )
        return result

    def update_on_device(self):
        params = self.want.api_params()
        result = self.client.api.tm.ltm.monitor.tcp_echos.tcp_echo.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result.modify(**params)

    def create_on_device(self):
        params = self.want.api_params()
        self.client.api.tm.ltm.monitor.tcp_echos.tcp_echo.create(
            name=self.want.name,
            partition=self.want.partition,
            **params
        )

    def remove_from_device(self):
        result = self.client.api.tm.ltm.monitor.tcp_echos.tcp_echo.load(
            name=self.want.name,
            partition=self.want.partition
        )
        if result:
            result.delete()


# TODO: Remove this in 2.5 and put it its own module
class TcpHalfOpenManager(BaseManager):
    def __init__(self, client):
        self.client = client
        self.have = None
        self.want = ParametersHalfOpen(self.client.module.params)
        self.changes = ParametersHalfOpen()

    def _set_changed_options(self):
        changed = {}
        for key in ParametersHalfOpen.returnables:
            if getattr(self.want, key) is not None:
                changed[key] = getattr(self.want, key)
        if changed:
            self.changes = ParametersHalfOpen(changed)

    def _update_changed_options(self):
        diff = Difference(self.want, self.have)
        updatables = ParametersHalfOpen.updatables
        changed = dict()
        for k in updatables:
            change = diff.compare(k)
            if change is None:
                continue
            else:
                changed[k] = change
        if changed:
            self.changes = ParametersHalfOpen(changed)
            return True
        return False

    def read_current_from_device(self):
        resource = self.client.api.tm.ltm.monitor.tcp_half_opens.tcp_half_open.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result = resource.attrs
        return ParametersHalfOpen(result)

    def exists(self):
        result = self.client.api.tm.ltm.monitor.tcp_half_opens.tcp_half_open.exists(
            name=self.want.name,
            partition=self.want.partition
        )
        return result

    def update_on_device(self):
        params = self.want.api_params()
        result = self.client.api.tm.ltm.monitor.tcp_half_opens.tcp_half_open.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result.modify(**params)

    def create_on_device(self):
        params = self.want.api_params()
        self.client.api.tm.ltm.monitor.tcp_half_opens.tcp_half_open.create(
            name=self.want.name,
            partition=self.want.partition,
            **params
        )

    def remove_from_device(self):
        result = self.client.api.tm.ltm.monitor.tcp_half_opens.tcp_half_open.load(
            name=self.want.name,
            partition=self.want.partition
        )
        if result:
            result.delete()


class ArgumentSpec(object):
    def __init__(self):
        self.supports_check_mode = True
        self.argument_spec = dict(
            name=dict(required=True),

            # Make this assume "tcp" in the partition specified. The user
            # is required to specify the full path if they want to use a different
            # partition.
            parent=dict(),

            send=dict(),
            receive=dict(),
            ip=dict(),
            port=dict(type='int'),
            interval=dict(type='int'),
            timeout=dict(type='int'),
            time_until_up=dict(type='int'),

            # Deprecated params
            type=dict(
                default='tcp',
                removed_in_version='2.4',
                choices=[
                    'tcp', 'TTYPE_TCP', 'TTYPE_TCP_ECHO', 'TTYPE_TCP_HALF_OPEN'
                ]
            ),
            parent_partition=dict(
                default='Common',
                removed_in_version='2.4'
            )
        )
        self.f5_product_name = 'bigip'
        self.mutually_exclusive = [
            ['parent', 'parent_partition']
        ]


def main():
    if not HAS_F5SDK:
        raise F5ModuleError("The python f5-sdk module is required")

    spec = ArgumentSpec()

    client = AnsibleF5Client(
        argument_spec=spec.argument_spec,
        supports_check_mode=spec.supports_check_mode,
        f5_product_name=spec.f5_product_name,
        mutually_exclusive=spec.mutually_exclusive
    )

    try:
        mm = ModuleManager(client)
        results = mm.exec_module()
        client.module.exit_json(**results)
    except F5ModuleError as e:
        client.module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
