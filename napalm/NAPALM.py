#!/opt/ipeng/ENV/bin/python3

"""
Provide connection to a network device using NAPALM

USAGE: napalm_connection.open(devicename, ostype)

John Tishey - 2018
"""

from napalm import get_network_driver
from ltoken import ltoken
from get_os import get_os

def open(dev):
    """
    Open a connection to a network device using NAPALM
    Created so I don't have to keep remembering the format/os_types
    As well as trying telnet each time before SSH for IOS to avoid 
    paramiko errors on IOS devices that don't have SSH properly configured.

    Example:
    from napalm import NAPALM
    device = NAPALM.open('vSRX1')

    You'll now have an open connection to the device vSRX1

    Requires 2 custom modules ltoken and get_os
    """

    auth_info = ltoken()
    dev_os = get_os(dev, format='napalm')
    if 'Unable' in dev_os:
        print(dev_os)
        return

    driver = get_network_driver(dev_os)

    # Try telnet first for IOS so paramiko doesn't barf
    if dev_os == 'ios':
        try:
            device = driver(dev, auth_info['username'], auth_info['password'], optional_args={'transport':'telnet'})
            device.open()
        except:
            device = driver(dev, auth_info['username'], auth_info['password'])
    else:
        device = driver(dev, auth_info['username'], auth_info['password'])
        
    device.open()
    return device
