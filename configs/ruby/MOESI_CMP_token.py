# Copyright (c) 2006-2007 The Regents of The University of Michigan
# Copyright (c) 2009 Advanced Micro Devices, Inc.
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
# Authors: Brad Beckmann

import math
import m5
from m5.objects import *
from m5.defines import buildEnv
from Ruby import create_topology
#from Ruby import create_vtopology
#
# Note: the L1 Cache latency is only used by the sequencer on fast path hits
#
class L1Cache(RubyCache):
    latency = 2

#
# Note: the L2 Cache latency is not currently used
#
class L2Cache(RubyCache):
    latency = 10

def define_options(parser):
    parser.add_option("--l1-retries", type="int", default=1,
                      help="Token_CMP: # of l1 retries before going persistent")
    parser.add_option("--timeout-latency", type="int", default=300,
                      help="Token_CMP: cycles until issuing again");
    parser.add_option("--disable-dyn-timeouts", action="store_true",
          help="Token_CMP: disable dyanimc timeouts, use fixed latency instead")
    parser.add_option("--allow-atomic-migration", action="store_true",
          help="allow migratory sharing for atomic only accessed blocks")
 

def create_vsystem(options, systems, ruby_system, total_num_cpus, total_mem_size, vm_cpus, vm_mems):
    
    if buildEnv['PROTOCOL'] != 'MOESI_CMP_token':
        panic("This script requires the MOESI_CMP_token protocol to be built.")

    #
    # number of tokens that the owner passes to requests so that shared blocks can
    # respond to read requests
    #
    n_tokens = total_num_cpus + 1

    cpu_sequencers = []
    
    #
    # The ruby network creation expects the list of nodes in the system to be
    # consistent with the NetDest list.  Therefore the l1 controller nodes must be
    # listed before the directory nodes and directory nodes before dma nodes, etc.
    #
    l1_cntrl_nodes = []
    l2_cntrl_nodes = []
    dir_cntrl_nodes = []
    dma_cntrl_nodes = []

    #
    # Must create the individual controllers before the network to ensure the
    # controller constructors are called before the network constructor
    #
    l2_bits = int(math.log(options.num_l2caches, 2))
    block_size_bits = int(math.log(options.cacheline_size, 2))
    
    cntrl_count = 0

    start_address = MemorySize("0B")

    for (j, vm) in enumerate(systems):
        for i in xrange(int(vm_cpus[j])):
            #
            # First create the Ruby objects associated with this cpu
            #
            l1i_cache = L1Cache(size = options.l1i_size,
                                assoc = options.l1i_assoc,
                                start_index_bit = block_size_bits)
            l1d_cache = L1Cache(size = options.l1d_size,
                                assoc = options.l1d_assoc,
                                start_index_bit = block_size_bits)

            l1_cntrl = L1Cache_Controller(version = len(l1_cntrl_nodes),
                                      cntrl_id = cntrl_count,
                                      L1IcacheMemory = l1i_cache,
                                      L1DcacheMemory = l1d_cache,
                                      l2_select_num_bits = l2_bits,
                                      N_tokens = n_tokens,
                                      retry_threshold = \
                                        options.l1_retries,
                                      fixed_timeout_latency = \
                                        options.timeout_latency,
                                      dynamic_timeout_enabled = \
                                        not options.disable_dyn_timeouts,
                                      no_mig_atomic = not \
                                        options.allow_atomic_migration,
                                      send_evictions = (
                                          options.cpu_type == "detailed"),
                                      ruby_system = ruby_system)

            cpu_seq = RubySequencer(version = len(l1_cntrl_nodes),
                                icache = l1i_cache,
                                dcache = l1d_cache,
                                ruby_system = ruby_system,
                                virtualization_support = True,
                                real_address_range = AddrRange(start_address,start_address.value+MemorySize(vm_mems[j]).value))

            l1_cntrl.sequencer = cpu_seq

            if vm.piobus != None:
                cpu_seq.pio_port = vm.piobus.slave

            exec("vm.l1_cntrl%d = l1_cntrl" % len(l1_cntrl_nodes))
            #
            # Add controllers and sequencers to the appropriate lists
            #
            cpu_sequencers.append(cpu_seq)
            l1_cntrl_nodes.append(l1_cntrl)

            cntrl_count += 1

        start_address.value = start_address.value + MemorySize(vm_mems[j]).value
        #print start_address

    l2_index_start = block_size_bits + l2_bits

    for i in xrange(options.num_l2caches):
        #
        # First create the Ruby objects associated with this cpu
        #
        l2_cache = L2Cache(size = options.l2_size,
                           assoc = options.l2_assoc,
                           start_index_bit = l2_index_start)

        l2_cntrl = L2Cache_Controller(version = i,
                                      cntrl_id = cntrl_count,
                                      L2cacheMemory = l2_cache,
                                      N_tokens = n_tokens,
                                      ruby_system = ruby_system)
        
        exec("systems[0].l2_cntrl%d = l2_cntrl" % i)
        l2_cntrl_nodes.append(l2_cntrl)

        cntrl_count += 1
    
    #TODO: take care of phys_mem_size
    phys_mem_size = total_mem_size
    mem_module_size = phys_mem_size / options.num_dirs
    
    for i in xrange(options.num_dirs):
        #
        # Create the Ruby objects associated with the directory controller
        #

        mem_cntrl = RubyMemoryControl(version = i,
                                      ruby_system = ruby_system)

        dir_size = MemorySize('0B')
        dir_size.value = mem_module_size

        dir_cntrl = Directory_Controller(version = i,
                                         cntrl_id = cntrl_count,
                                         directory = \
                                         RubyDirectoryMemory(version = i,
                                                             size = dir_size),
                                         memBuffer = mem_cntrl,
                                         l2_select_num_bits = l2_bits,
                                         ruby_system = ruby_system)
        
        exec("systems[0].dir_cntrl%d = dir_cntrl" % i)
        dir_cntrl_nodes.append(dir_cntrl)

        cntrl_count += 1

    for (j, vm) in enumerate(systems):
        for i, dma_port in enumerate(vm._dma_ports):
            #
            # Create the Ruby objects associated with the dma controller
            #
            dma_seq = DMASequencer(version = len(dma_cntrl_nodes),
                               ruby_system = ruby_system)
        
            dma_cntrl = DMA_Controller(version = len(dma_cntrl_nodes),
                                   cntrl_id = cntrl_count,
                                   dma_sequencer = dma_seq,
                                   ruby_system = ruby_system)
            
            exec("vm.dma_cntrl%d = dma_cntrl" % len(dma_cntrl_nodes))
            exec("vm.dma_cntrl%d.dma_sequencer.slave = dma_port" % len(dma_cntrl_nodes))
            dma_cntrl_nodes.append(dma_cntrl)
            cntrl_count += 1

    all_cntrls = l1_cntrl_nodes + \
                 l2_cntrl_nodes + \
                 dir_cntrl_nodes + \
                 dma_cntrl_nodes

    topology = create_topology(all_cntrls, options)

    return (cpu_sequencers, dir_cntrl_nodes, topology)
   
def create_system(options, system, piobus, dma_ports, ruby_system):
    
    if buildEnv['PROTOCOL'] != 'MOESI_CMP_token':
        panic("This script requires the MOESI_CMP_token protocol to be built.")

    #
    # number of tokens that the owner passes to requests so that shared blocks can
    # respond to read requests
    #
    n_tokens = options.num_cpus + 1

    cpu_sequencers = []
    
    #
    # The ruby network creation expects the list of nodes in the system to be
    # consistent with the NetDest list.  Therefore the l1 controller nodes must be
    # listed before the directory nodes and directory nodes before dma nodes, etc.
    #
    l1_cntrl_nodes = []
    l2_cntrl_nodes = []
    dir_cntrl_nodes = []
    dma_cntrl_nodes = []

    #
    # Must create the individual controllers before the network to ensure the
    # controller constructors are called before the network constructor
    #
    l2_bits = int(math.log(options.num_l2caches, 2))
    block_size_bits = int(math.log(options.cacheline_size, 2))
    
    cntrl_count = 0

    for i in xrange(options.num_cpus):
        #
        # First create the Ruby objects associated with this cpu
        #
        l1i_cache = L1Cache(size = options.l1i_size,
                            assoc = options.l1i_assoc,
                            start_index_bit = block_size_bits)
        l1d_cache = L1Cache(size = options.l1d_size,
                            assoc = options.l1d_assoc,
                            start_index_bit = block_size_bits)

        l1_cntrl = L1Cache_Controller(version = i,
                                      cntrl_id = cntrl_count,
                                      L1IcacheMemory = l1i_cache,
                                      L1DcacheMemory = l1d_cache,
                                      l2_select_num_bits = l2_bits,
                                      N_tokens = n_tokens,
                                      retry_threshold = \
                                        options.l1_retries,
                                      fixed_timeout_latency = \
                                        options.timeout_latency,
                                      dynamic_timeout_enabled = \
                                        not options.disable_dyn_timeouts,
                                      no_mig_atomic = not \
                                        options.allow_atomic_migration,
                                      send_evictions = (
                                          options.cpu_type == "detailed"),
                                      ruby_system = ruby_system)
        #temp changes
        cpu_seq = RubySequencer(version = i,
                                icache = l1i_cache,
                                dcache = l1d_cache,
                                ruby_system = ruby_system)#,
                                #virtualization_support = True,
                                #real_address_range = AddrRange(128*1024*1024,256*1024*1024))

        l1_cntrl.sequencer = cpu_seq

        if piobus != None:
            cpu_seq.pio_port = piobus.slave

        exec("system.l1_cntrl%d = l1_cntrl" % i)
        #
        # Add controllers and sequencers to the appropriate lists
        #
        cpu_sequencers.append(cpu_seq)
        l1_cntrl_nodes.append(l1_cntrl)

        cntrl_count += 1

    l2_index_start = block_size_bits + l2_bits

    for i in xrange(options.num_l2caches):
        #
        # First create the Ruby objects associated with this cpu
        #
        l2_cache = L2Cache(size = options.l2_size,
                           assoc = options.l2_assoc,
                           start_index_bit = l2_index_start)

        l2_cntrl = L2Cache_Controller(version = i,
                                      cntrl_id = cntrl_count,
                                      L2cacheMemory = l2_cache,
                                      N_tokens = n_tokens,
                                      ruby_system = ruby_system)
        
        exec("system.l2_cntrl%d = l2_cntrl" % i)
        l2_cntrl_nodes.append(l2_cntrl)

        cntrl_count += 1
        
    phys_mem_size = sum(map(lambda mem: mem.range.size(),
                            system.memories.unproxy(system)))
    mem_module_size = phys_mem_size / options.num_dirs

    for i in xrange(options.num_dirs):
        #
        # Create the Ruby objects associated with the directory controller
        #

        mem_cntrl = RubyMemoryControl(version = i,
                                      ruby_system = ruby_system)

        dir_size = MemorySize('0B')
        dir_size.value = mem_module_size

        dir_cntrl = Directory_Controller(version = i,
                                         cntrl_id = cntrl_count,
                                         directory = \
                                         RubyDirectoryMemory(version = i,
                                                             size = dir_size),
                                         memBuffer = mem_cntrl,
                                         l2_select_num_bits = l2_bits,
                                         ruby_system = ruby_system)

        exec("system.dir_cntrl%d = dir_cntrl" % i)
        dir_cntrl_nodes.append(dir_cntrl)

        cntrl_count += 1

    for i, dma_port in enumerate(dma_ports):
        #
        # Create the Ruby objects associated with the dma controller
        #

        #temp changes
        dma_seq = DMASequencer(version = i,
                               ruby_system = ruby_system,
                               virtualization_support = True)#,
                               #real_address_range = AddrRange(128*1024*1024,256*1024*1024))
        
        dma_cntrl = DMA_Controller(version = i,
                                   cntrl_id = cntrl_count,
                                   dma_sequencer = dma_seq,
                                   ruby_system = ruby_system)

        exec("system.dma_cntrl%d = dma_cntrl" % i)
        exec("system.dma_cntrl%d.dma_sequencer.slave = dma_port" % i)
        dma_cntrl_nodes.append(dma_cntrl)
        cntrl_count += 1

    all_cntrls = l1_cntrl_nodes + \
                 l2_cntrl_nodes + \
                 dir_cntrl_nodes + \
                 dma_cntrl_nodes

    topology = create_topology(all_cntrls, options)

    return (cpu_sequencers, dir_cntrl_nodes, topology)
