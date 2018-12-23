"""NAPALM Nokia SR-OS Handler."""
# Copyright 2015 Spotify AB. All rights reserved.
#
# The contents of this file are licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the
# License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

from __future__ import print_function
from __future__ import unicode_literals

import copy
import functools
import os
import re
import socket
import telnetlib
import tempfile
import uuid
from collections import defaultdict

from netmiko import FileTransfer, InLineTransfer

import napalm.base.constants as C
import napalm.base.helpers
from napalm.base.base import NetworkDriver
from napalm.base.exceptions import ReplaceConfigException, MergeConfigException, \
    ConnectionClosedException, CommandErrorException
from napalm.base.helpers import canonical_interface_name
from napalm.base.helpers import textfsm_extractor
from napalm.base.netmiko_helpers import netmiko_args
from napalm.base.utils import py23_compat


class SROSDriver(NetworkDriver):
    """NAPALM Nokia SROS Handler."""

    def __init__(self, hostname, username, password, timeout=60, optional_args=None):
        """NAPALM Nokia SROS Handler."""
        if optional_args is None:
            optional_args = {}
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout

        self.transport = optional_args.get('transport', 'ssh')
        self.netmiko_optional_args = netmiko_args(optional_args)
        # Set the default port if not set
        default_port = {
            'ssh': 22,
            'telnet': 23
        }
        self.netmiko_optional_args.setdefault('port', default_port[self.transport])

        self.device = None
        self.config_replace = False

        self.profile = ["sros"]
        self.use_canonical_interface = optional_args.get('canonical_int', False)

    def open(self):
        """Open a connection to the device."""
        device_type = 'alcatel_sros'
        self.device = self._netmiko_open(
            device_type,
            netmiko_optional_args=self.netmiko_optional_args,
        )

    def _netmiko_close(self):
        """Standardized method of closing a Netmiko connection."""
        self.device.disconnect()
        self._netmiko_device = None
        self.device = None

    def close(self):
        """Close the connection to the device."""
        self._netmiko_close()

    def _send_command(self, command):
        """Wrapper for self.device.send.command().

        If command is a list will iterate through commands until valid command.
        """
        try:
            if isinstance(command, list):
                for cmd in command:
                    output = self.device.send_command(cmd)
                    if 'Bad command' not in output and 'CLI Invalid' not in output:
                        break
            else:
                output = self.device.send_command(command)
            return self._send_command_postprocess(output)
        except (socket.error, EOFError) as e:
            raise ConnectionClosedException(str(e))

    def _send_config_set(self, command):
        """Wrapper for self.device.send_config_set().

        Requires a list of configuration commands
        """
        try:
            output = self.device.send_config_set(command)
            return output
        except (socket.error, EOFError) as e:
            raise ConnectionClosedException(str(e))

    def is_alive(self):
        """Returns a flag with the state of the connection."""
        null = chr(0)
        if self.device is None:
            return {'is_alive': False}
        if self.transport == 'telnet':
            try:
                # Try sending IAC + NOP (IAC is telnet way of sending command
                # IAC = Interpret as Command (it comes before the NOP)
                self.device.write_channel(telnetlib.IAC + telnetlib.NOP)
                return {'is_alive': True}
            except UnicodeDecodeError:
                # Netmiko logging bug (remove after Netmiko >= 1.4.3)
                return {'is_alive': True}
            except AttributeError:
                return {'is_alive': False}
        else:
            # SSH
            try:
                # Try sending ASCII null byte to maintain the connection alive
                self.device.write_channel(null)
                return {'is_alive': self.device.remote_conn.transport.is_active()}
            except (socket.error, EOFError):
                # If unable to send, we can tell for sure that the connection is unusable
                return {'is_alive': False}
        return {'is_alive': False}

    @staticmethod
    def _send_command_postprocess(output):
        """
        Cleanup actions on send_command() for NAPALM getters.

        Remove "Load for five sec; one minute if in output"
        Remove "Time source is"
        """
        output = re.sub(r"^Load for five secs.*$", "", output, flags=re.M)
        output = re.sub(r"^Time source is .*$", "", output, flags=re.M)
        return output.strip()

    def save_config(self):
        """ Issues 'admin save' command to save the config to disk  """
        try:
            output = self._send_command(['admin save'])
            return output
        except (socket.error, EOFError) as e:
            raise ConnectionClosedException(str(e))
    
    def config_commands(self, commands):
        """ Execute a list of configuration commands and return the output as a string

        Example input:
        ['port 1/1/3', 'description "very nice"','no shutdown']

        Output example:
        A:7750-1# 
        A:7750-1>config# port 1/1/3 
        A:7750-1>config>port# description "very nice"
        *A:7750-1>config>port# no shutdown 
        *A:7750-1>config>port# exit all 
        *A:7750-1# 
        """
        if type(commands) is not list:
            raise TypeError('Please enter a valid list of commands!')
        cfg_output = self._send_config_set(commands)
        return cfg_output

    def cli(self, commands):
        """
        Execute a list of commands and return the output in a dictionary format using the command
        as the key.

        Example input:
        ['show uptime', 'show users']

        Output example:
        {   'show uptime': '\nSystem Up Time         : 0 days, 00:01:44.31 (hr:min:sec)',
            'show users': ' \nConsole         --               0d 00:02:05    \n  --                                                                            \nguest           SSHv2   17DEC2018 05:18:10     0d 00:00:00    \n  172.16.212.49'
        }
        """
        cli_output = dict()
        if type(commands) is not list:
            raise TypeError('Please enter a valid list of commands!')

        for command in commands:
            output = self._send_command(command)
            if 'Bad command' in output or 'CLI Invalid' in output:
                raise ValueError('Unable to execute command "{}"'.format(command))
            cli_output.setdefault(command, {})
            cli_output[command] = output
        return cli_output

    def get_config(self, retrieve='all'):
        """Implementation of get_config for SROS.

        Startup and candidate configs will be an empty string for now.  Plans to check the bof
        and output the config specified there as startup.
        """

        configs = {
            'startup': '',
            'running': '',
            'candidate': '',
        }

        if retrieve in ('running', 'all'):
            command = 'admin display-config'
            output = self._send_command(command)
            configs['running'] = output

        return configs


    
    def get_optics(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_lldp_neighbors(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_lldp_neighbors_detail(self, interface=''):
        raise NotImplementedError('Not implemented for this platform')
    def parse_uptime(self, uptime_str):
        raise NotImplementedError('Not implemented for this platform')
    def get_facts(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_interfaces(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_interfaces_ip(self):
        raise NotImplementedError('Not implemented for this platform')
    def bgp_time_conversion(self, bgp_uptime):
        raise NotImplementedError('Not implemented for this platform')
    def get_bgp_neighbors(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_bgp_neighbors_detail(self, neighbor_address=''):
        raise NotImplementedError('Not implemented for this platform')
    def get_interfaces_counters(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_environment(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_arp_table(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_ntp_peers(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_ntp_servers(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_ntp_stats(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_mac_address_table(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_probes_config(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_snmp_information(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_users(self):
        raise NotImplementedError('Not implemented for this platform')
    def ping(self):
        raise NotImplementedError('Not implemented for this platform')
    def traceroute(self):
        raise NotImplementedError('Not implemented for this platform')
    def get_network_instances(self, name=''):
        raise NotImplementedError('Not implemented for this platform')
    def get_ipv6_neighbors_table(self):
        raise NotImplementedError('Not implemented for this platform')
    def dest_file_system(self):
        raise NotImplementedError('Not implemented for this platform')
    def load_replace_candidate(self, filename=None, config=None):
        raise NotImplementedError('Not implemented for this platform')
    def load_merge_candidate(self, filename=None, config=None):
        raise NotImplementedError('Not implemented for this platform')
    def compare_config(self):
        raise NotImplementedError('Not implemented for this platform')
    def commit_config(self, message=""):
        raise NotImplementedError('Not implemented for this platform')
    def discard_config(self):
        raise NotImplementedError('Not implemented for this platform')
    def rollback(self):
        raise NotImplementedError('Not implemented for this platform')
