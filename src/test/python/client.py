# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/test/python/client.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright © 2012 Matthew W. Samsonoff <matthew.samsonoff@makerbot.com>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, print_function, unicode_literals)

import argparse
import sys
import threading

import conveyor.address
import conveyor.connection

def _main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('address', metavar='ADDRESS')
    parsedargs = parser.parse_args(argv[1:])
    address = conveyor.address.Address.parse(parsedargs.address)
    connection = address.connect()
    connection.write('hello from client')
    def target():
        while True:
            data = sys.stdin.readline()
            if '' == data:
                break
            else:
                connection.write(data)
    thread = threading.Thread(target=target)
    thread.start()
    while True:
        data = connection.read()
        if '' == data:
            break
        else:
            print('data=%r' % (data,))
    return 0

if '__main__' == __name__:
    code = _main(sys.argv)
    if None is code:
        code = 0
    sys.exit(code)
