#!/opt/ipeng/ENV/bin/python3

from napalm.ios.ios import IOSDriver

class CustomIOSDriver(IOSDriver):
    """Custom NAPALM Cisco IOS Handler."""

    def _send_config_set(self, command):
        """Wrapper for self.device.send_config_set().

        Requires a list of configuration commands
        """
        try:
            output = self.device.send_config_set(command)
            return output
        except (socket.error, EOFError) as e:
            raise ConnectionClosedException(str(e))

    def config_commands(self, commands):
        """ Execute a list of configuration commands and return the output as a string

        Example input:
        ['interface Gi3', 'description horse','no shutdown']

        Output example:
        config term
        Enter configuration commands, one per line.  End with CNTL/Z.
        IOS-R1(config)#interface Gi3
        IOS-R1(config-if)#description horse
        IOS-R1(config-if)#no shutdown
        IOS-R1(config-if)#end
        IOS-R1#

        """
        if type(commands) is not list:
            raise TypeError('Please enter a valid list of commands!')
        cfg_output = self._send_config_set(commands)
        return cfg_output

    def save_config(self):
        """Sends "wr mem" to the device to save the running config """
        try:
            output = self.device.save_config()
            return output
        except (socket.error, EOFError) as e:
            raise ConnectionClosedException(str(e))
    