# Copyright (c) 2010 Advanced Micro Devices, Inc.
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

from m5.params import *
from m5.objects import *

from BaseTopology import SimpleTopology

class Mesh(SimpleTopology):
    description='Mesh'

    def __init__(self, controllers):
        self.nodes = controllers

    # Makes a generic mesh assuming an equal number of cache and directory cntrls

    def makeTopology(self, options, IntLink, ExtLink, Router):
        nodes = self.nodes

        num_routers = options.num_cpus
        num_rows = options.mesh_rows

        # There must be an evenly divisible number of cntrls to routers
        # Also, obviously the number or rows must be <= the number of routers
        cntrls_per_router, remainder = divmod(len(nodes), num_routers)
        assert(num_rows <= num_routers)
        num_columns = int(num_routers / num_rows)
        assert(num_columns * num_rows == num_routers)

        # Create the routers in the mesh
        routers = [Router(router_id=i) for i in range(num_routers)]

        # link counter to set unique link ids
        link_count = 0

        # Add all but the remainder nodes to the list of nodes to be uniformly
        # distributed across the network.
        network_nodes = []
        remainder_nodes = []
        for node_index in xrange(len(nodes)):
            if node_index < (len(nodes) - remainder):
                network_nodes.append(nodes[node_index])
            else:
                remainder_nodes.append(nodes[node_index])

        # Connect each node to the appropriate router
        ext_links = []
        for (i, n) in enumerate(network_nodes):
            cntrl_level, router_id = divmod(i, num_routers)
            assert(cntrl_level < cntrls_per_router)
            ext_links.append(ExtLink(link_id=link_count, ext_node=n,
                                    int_node=routers[router_id]))
            link_count += 1

        # Connect the remainding nodes to router 0.  These should only be
        # DMA nodes.
        for (i, node) in enumerate(remainder_nodes):
            assert(node.type == 'DMA_Controller')
            assert(i < remainder)
            ext_links.append(ExtLink(link_id=link_count, ext_node=node,
                                    int_node=routers[0]))
            link_count += 1

        # Create the mesh links.  First row (east-west) links then column
        # (north-south) links
        int_links = []
        for row in xrange(num_rows):
            for col in xrange(num_columns):
                if (col + 1 < num_columns):
                    east_id = col + (row * num_columns)
                    west_id = (col + 1) + (row * num_columns)
                    int_links.append(IntLink(link_id=link_count,
                                            node_a=routers[east_id],
                                            node_b=routers[west_id],
                                            weight=1))
                    link_count += 1

        for col in xrange(num_columns):
            for row in xrange(num_rows):
                if (row + 1 < num_rows):
                    north_id = col + (row * num_columns)
                    south_id = col + ((row + 1) * num_columns)
                    int_links.append(IntLink(link_id=link_count,
                                            node_a=routers[north_id],
                                            node_b=routers[south_id],
                                            weight=2))
                    link_count += 1
        return routers, int_links, ext_links

    def makevTopology(self, options, IntLink, ExtLink, Router, vmm_cpu_matrix):
        nodes = self.nodes

        num_routers = len(vmm_cpu_matrix[0])
        num_rows = options.mesh_rows

        total_vcpu = 0
        for i in xrange(len(vmm_cpu_matrix)):
            for j in xrange(len(vmm_cpu_matrix[i])):
                 if float(vmm_cpu_matrix[i][j]) > 0:
                     total_vcpu += 1

        # There must be an evenly divisible number of cntrls to routers
        # Also, obviously the number or rows must be <= the number of routers
        cntrls_per_router, remainder = divmod(len(nodes)+num_routers-total_vcpu, num_routers)
        assert(num_rows <= num_routers)
        num_columns = int(num_routers / num_rows)
        assert(num_columns * num_rows == num_routers)

        # Create the mesh object
        #mesh = Mesh()
 
        # Create the routers in the mesh
        routers = [Router(router_id=i) for i in range(num_routers)]

        # link counter to set unique link ids
        link_count = 0

        # Add all but the remainder nodes to the list of nodes to be uniformly
        # distributed across the network.
        network_nodes = []
        remainder_nodes = []

        #print vmm_cpu_matrix

        node_index = 0
        for i in xrange(len(vmm_cpu_matrix[0])):
            network_nodes.append([])
            for j in xrange(len(vmm_cpu_matrix)):
                 if(float(vmm_cpu_matrix[j][i]) > 0):
                      network_nodes[i].append(nodes[node_index])
                      node_index += 1

        for i in xrange( len(nodes) - node_index ):
            if node_index < (len(nodes) - remainder):
                 network_nodes.append([])
                 network_nodes[len(network_nodes)-1].append(nodes[node_index])
            else:
                 remainder_nodes.append(nodes[node_index])
            node_index += 1 

        #print "network nodes"
        #print network_nodes
        #print "remainder nodes"
        #print remainder_nodes

        # Connect each node to the appropriate router
        ext_links = []
        for (i, node_array) in enumerate(network_nodes):
            cntrl_level, router_id = divmod(i, num_routers)
            assert(cntrl_level < cntrls_per_router)
            for (j, node) in enumerate(node_array):
                 ext_links.append(ExtLink(link_id=link_count, ext_node=node,
                                     int_node=routers[router_id]))
            link_count += 1

        # Connect the remainding nodes to router 0.  These should only be
        # DMA nodes.
        for (i, node) in enumerate(remainder_nodes):
            #assert(node.type == 'DMA_Controller')
            assert(i < remainder)
            ext_links.append(ExtLink(link_id=link_count, ext_node=node,
                                     int_node=routers[0]))
            link_count += 1

        # Create the mesh links.  First row (east-west) links then column
        # (north-south) links
        int_links = []
        for row in xrange(num_rows):
            for col in xrange(num_columns):
                if (col + 1 < num_columns):
                    east_id = col + (row * num_columns)
                    west_id = (col + 1) + (row * num_columns)
                    int_links.append(IntLink(link_id=link_count,
                                             node_a=routers[east_id],
                                             node_b=routers[west_id],
                                             weight=1))
                    link_count += 1
                
        for col in xrange(num_columns):
            for row in xrange(num_rows):
                if (row + 1 < num_rows):
                    north_id = col + (row * num_columns)
                    south_id = col + ((row + 1) * num_columns)
                    int_links.append(IntLink(link_id=link_count,
                                             node_a=routers[north_id],
                                             node_b=routers[south_id],
                                             weight=2))
                    link_count += 1

        return routers, int_links, ext_links