# Copyright (c) 2006-2007 The Regents of The University of Michigan
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Authors: Steve Reinhardt

import m5
from m5.objects import *
m5.util.addToPath('../configs/common')
import FSConfig
from Caches import *

#cpu
cpus = [ DerivO3CPU(cpu_id=i) for i in xrange(2) ]
#the system
system = FSConfig.makeLinuxAlphaSystem('timing')

system.cpu = cpus
#create the l1/l2 bus
system.toL2Bus = CoherentBus(clock = '2GHz')
system.iocache = IOCache(clock = '1GHz', addr_ranges = [AddrRange('8GB')])
system.iocache.cpu_side = system.iobus.master
system.iocache.mem_side = system.membus.slave


#connect up the l2 cache
system.l2c = L2(clock = '2GHz', size='4MB', assoc=8)
system.l2c.cpu_side = system.toL2Bus.master
system.l2c.mem_side = system.membus.slave

#connect up the cpu and l1s
for c in cpus:
    c.addPrivateSplitL1Caches(L1(size = '32kB', assoc = 1),
                                L1(size = '32kB', assoc = 4))
    # create the interrupt controller
    c.createInterruptController()
    # connect cpu level-1 caches to shared level-2 cache
    c.connectAllPorts(system.toL2Bus, system.membus)
    c.clock = '2GHz'

root = Root(full_system=True, system=system)
m5.ticks.setGlobalFrequency('1THz')

