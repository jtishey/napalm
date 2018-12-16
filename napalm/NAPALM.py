#!/opt/ipeng/ENV/bin/python3

"""
Provide connection to a network device using NAPALM

USAGE: napalm_connection.open(devicename, ostype)

John Tishey - 2018
"""

from napalm import get_network_driver
from ltoken import ltoken


def open(dev, dev_os):
    """
    Open a connection to a network device using NAPALM
    Created so I don't have to keep remembering the format/os_types
    As well as trying telnet each time before SSH for IOS to avoid 
    paramiko errors on IOS devices that don't have SSH properly configured.

    Supports ios, iosxr, junos, and nxos device types

    Example:  
    from napalm import napalm_connection
    device = napalm_connection('vSRX1', junos)

    You'll now have an open connection to the device vSRX1
    """
    auth_info = ltoken()
    # Convert the dev_os to a stadard format needed by napalm
    if dev_os == 'XR':
        dev_os = 'iosxr'
    elif dev_os == 'JUNIPER':
        dev_os = 'junos'
    else:
        dev_os = dev_os.lower()
    
    driver = get_network_driver(dev_os)

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
