/*
 * Copyright (c) 2012 ARM Limited
 * All rights reserved
 *
 * The license below extends only to copyright in the software and shall
 * not be construed as granting a license to any other intellectual
 * property including but not limited to intellectual property relating
 * to a hardware implementation of the functionality of the software
 * licensed hereunder.  You may use the software subject to the license
 * terms below provided that you ensure that this notice is replicated
 * unmodified and in its entirety in all distributions of the software,
 * modified or unmodified, in source code or in binary form.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 * Authors: Thomas Grass
 *          Andreas Hansson
 */

#include "debug/CommMonitor.hh"
#include "mem/comm_monitor.hh"
#include "sim/stats.hh"

CommMonitor::CommMonitor(Params* params)
    : MemObject(params),
      masterPort(name() + "-master", *this),
      slavePort(name() + "-slave", *this),
      samplePeriodicEvent(this),
      samplePeriodTicks(params->sample_period),
      readAddrMask(params->read_addr_mask),
      writeAddrMask(params->write_addr_mask),
      stats(params)
{
    // keep track of the sample period both in ticks and absolute time
    samplePeriod.setTick(params->sample_period);

    DPRINTF(CommMonitor,
            "Created monitor %s with sample period %d ticks (%f s)\n",
            name(), samplePeriodTicks, samplePeriod);
}

CommMonitor*
CommMonitorParams::create()
{
    return new CommMonitor(this);
}

void
CommMonitor::init()
{
    // make sure both sides of the monitor are connected
    if (!slavePort.isConnected() || !masterPort.isConnected())
        fatal("Communication monitor is not connected on both sides.\n");
}

BaseMasterPort&
CommMonitor::getMasterPort(const std::string& if_name, PortID idx)
{
    if (if_name == "master") {
        return masterPort;
    } else {
        return MemObject::getMasterPort(if_name, idx);
    }
}

BaseSlavePort&
CommMonitor::getSlavePort(const std::string& if_name, PortID idx)
{
    if (if_name == "slave") {
        return slavePort;
    } else {
        return MemObject::getSlavePort(if_name, idx);
    }
}

void
CommMonitor::recvFunctional(PacketPtr pkt)
{
    masterPort.sendFunctional(pkt);
}

void
CommMonitor::recvFunctionalSnoop(PacketPtr pkt)
{
    slavePort.sendFunctionalSnoop(pkt);
}

Tick
CommMonitor::recvAtomic(PacketPtr pkt)
{
    return masterPort.sendAtomic(pkt);
}

Tick
CommMonitor::recvAtomicSnoop(PacketPtr pkt)
{
    return slavePort.sendAtomicSnoop(pkt);
}

bool
CommMonitor::recvTimingReq(PacketPtr pkt)
{
    // should always see a request
    assert(pkt->isRequest());

    // Store relevant fields of packet, because packet may be modified
    // or even deleted when sendTiming() is called.
    bool isRead = pkt->isRead();
    bool isWrite = pkt->isWrite();
    unsigned size = pkt->getSize();
    Addr addr = pkt->getAddr();
    bool needsResponse = pkt->needsResponse();
    bool memInhibitAsserted = pkt->memInhibitAsserted();
    Packet::SenderState* senderState = pkt->senderState;

    // If a cache miss is served by a cache, a monitor near the memory
    // would see a request which needs a response, but this response
    // would be inhibited and not come back from the memory. Therefore
    // we additionally have to check the inhibit flag.
    if (needsResponse && !memInhibitAsserted && !stats.disableLatencyHists) {
        pkt->senderState = new CommMonitorSenderState(senderState,
                                                      curTick());
    }

    // Attempt to send the packet (always succeeds for inhibited
    // packets)
    bool successful = masterPort.sendTimingReq(pkt);

    // If not successful, restore the sender state
    if (!successful && needsResponse && !stats.disableLatencyHists) {
        delete pkt->senderState;
        pkt->senderState = senderState;
    }

    if (successful && isRead) {
        DPRINTF(CommMonitor, "Forwarded read request\n");

        // Increment number of observed read transactions
        if (!stats.disableTransactionHists) {
            ++stats.readTrans;
        }

        // Get sample of burst length
        if (!stats.disableBurstLengthHists) {
            stats.readBurstLengthHist.sample(size);
        }

        // Sample the masked address
        if (!stats.disableAddrDists) {
            stats.readAddrDist.sample(addr & readAddrMask);
        }

        // If it needs a response increment number of outstanding read
        // requests
        if (!stats.disableOutstandingHists && needsResponse) {
            ++stats.outstandingReadReqs;
        }

        if (!stats.disableITTDists) {
            // Sample value of read-read inter transaction time
            if (stats.timeOfLastRead != 0) {
                stats.ittReadRead.sample(curTick() - stats.timeOfLastRead);
            }
            stats.timeOfLastRead = curTick();

            // Sample value of req-req inter transaction time
            if (stats.timeOfLastReq != 0) {
                stats.ittReqReq.sample(curTick() - stats.timeOfLastReq);
            }
            stats.timeOfLastReq = curTick();
        }
    } else if (successful && isWrite) {
        DPRINTF(CommMonitor, "Forwarded write request\n");

        // Same as for reads
        if (!stats.disableTransactionHists) {
            ++stats.writeTrans;
        }

        if (!stats.disableBurstLengthHists) {
            stats.writeBurstLengthHist.sample(size);
        }

        // Update the bandwidth stats on the request
        if (!stats.disableBandwidthHists) {
            stats.writtenBytes += size;
            stats.totalWrittenBytes += size;
        }

        // Sample the masked write address
        if (!stats.disableAddrDists) {
            stats.writeAddrDist.sample(addr & writeAddrMask);
        }

        if (!stats.disableOutstandingHists && needsResponse) {
            ++stats.outstandingWriteReqs;
        }

        if (!stats.disableITTDists) {
            // Sample value of write-to-write inter transaction time
            if (stats.timeOfLastWrite != 0) {
                stats.ittWriteWrite.sample(curTick() - stats.timeOfLastWrite);
            }
            stats.timeOfLastWrite = curTick();

            // Sample value of req-to-req inter transaction time
            if (stats.timeOfLastReq != 0) {
                stats.ittReqReq.sample(curTick() - stats.timeOfLastReq);
            }
            stats.timeOfLastReq = curTick();
        }
    } else if (successful) {
        DPRINTF(CommMonitor, "Forwarded non read/write request\n");
    }

    return successful;
}

bool
CommMonitor::recvTimingResp(PacketPtr pkt)
{
    // should always see responses
    assert(pkt->isResponse());

    // Store relevant fields of packet, because packet may be modified
    // or even deleted when sendTiming() is called.
    bool isRead = pkt->isRead();
    bool isWrite = pkt->isWrite();
    unsigned size = pkt->getSize();
    Tick latency = 0;
    CommMonitorSenderState* commReceivedState =
        dynamic_cast<CommMonitorSenderState*>(pkt->senderState);

    if (!stats.disableLatencyHists) {
        // Restore initial sender state
        if (commReceivedState == NULL)
            panic("Monitor got a response without monitor sender state\n");

        // Restore the sate
        pkt->senderState = commReceivedState->origSenderState;
    }

    // Attempt to send the packet
    bool successful = slavePort.sendTimingResp(pkt);

    if (!stats.disableLatencyHists) {
        // If packet successfully send, sample value of latency,
        // afterwards delete sender state, otherwise restore state
        if (successful) {
            latency = curTick() - commReceivedState->transmitTime;
            DPRINTF(CommMonitor, "Latency: %d\n", latency);
            delete commReceivedState;
        } else {
            // Don't delete anything and let the packet look like we
            // did not touch it
            pkt->senderState = commReceivedState;
        }
    }

    if (successful && isRead) {
        // Decrement number of outstanding read requests
        DPRINTF(CommMonitor, "Received read response\n");
        if (!stats.disableOutstandingHists) {
            assert(stats.outstandingReadReqs != 0);
            --stats.outstandingReadReqs;
        }

        if (!stats.disableLatencyHists) {
            stats.readLatencyHist.sample(latency);
        }

        // Update the bandwidth stats based on responses for reads
        if (!stats.disableBandwidthHists) {
            stats.readBytes += size;
            stats.totalReadBytes += size;
        }

    } else if (successful && isWrite) {
        // Decrement number of outstanding write requests
        DPRINTF(CommMonitor, "Received write response\n");
        if (!stats.disableOutstandingHists) {
            assert(stats.outstandingWriteReqs != 0);
            --stats.outstandingWriteReqs;
        }

        if (!stats.disableLatencyHists) {
            stats.writeLatencyHist.sample(latency);
        }
    } else if (successful) {
        DPRINTF(CommMonitor, "Received non read/write response\n");
    }
    return successful;
}

void
CommMonitor::recvTimingSnoopReq(PacketPtr pkt)
{
    slavePort.sendTimingSnoopReq(pkt);
}

bool
CommMonitor::recvTimingSnoopResp(PacketPtr pkt)
{
    return masterPort.sendTimingSnoopResp(pkt);
}

bool
CommMonitor::isSnooping() const
{
    // check if the connected master port is snooping
    return slavePort.isSnooping();
}

unsigned
CommMonitor::deviceBlockSizeMaster()
{
    return slavePort.peerBlockSize();
}

unsigned
CommMonitor::deviceBlockSizeSlave()
{
    return masterPort.peerBlockSize();
}

AddrRangeList
CommMonitor::getAddrRanges() const
{
    // get the address ranges of the connected slave port
    return masterPort.getAddrRanges();
}

void
CommMonitor::recvRetryMaster()
{
    slavePort.sendRetry();
}

void
CommMonitor::recvRetrySlave()
{
    masterPort.sendRetry();
}

void
CommMonitor::recvRangeChange()
{
    slavePort.sendRangeChange();
}

void
CommMonitor::regStats()
{
    // Initialise all the monitor stats
    using namespace Stats;

    stats.readBurstLengthHist
        .init(params()->burst_length_bins)
        .name(name() + ".readBurstLengthHist")
        .desc("Histogram of burst lengths of transmitted packets")
        .flags(stats.disableBurstLengthHists ? nozero : pdf);

    stats.writeBurstLengthHist
        .init(params()->burst_length_bins)
        .name(name() + ".writeBurstLengthHist")
        .desc("Histogram of burst lengths of transmitted packets")
        .flags(stats.disableBurstLengthHists ? nozero : pdf);

    // Stats based on received responses
    stats.readBandwidthHist
        .init(params()->bandwidth_bins)
        .name(name() + ".readBandwidthHist")
        .desc("Histogram of read bandwidth per sample period (bytes/s)")
        .flags(stats.disableBandwidthHists ? nozero : pdf);

    stats.averageReadBW
        .name(name() + ".averageReadBandwidth")
        .desc("Average read bandwidth (bytes/s)")
        .flags(stats.disableBandwidthHists ? nozero : pdf);

    stats.totalReadBytes
        .name(name() + ".totalReadBytes")
        .desc("Number of bytes read")
        .flags(stats.disableBandwidthHists ? nozero : pdf);

    stats.averageReadBW = stats.totalReadBytes / simSeconds;

    // Stats based on successfully sent requests
    stats.writeBandwidthHist
        .init(params()->bandwidth_bins)
        .name(name() + ".writeBandwidthHist")
        .desc("Histogram of write bandwidth (bytes/s)")
        .flags(stats.disableBandwidthHists ? (pdf | nozero) : pdf);

    stats.averageWriteBW
        .name(name() + ".averageWriteBandwidth")
        .desc("Average write bandwidth (bytes/s)")
        .flags(stats.disableBandwidthHists ? nozero : pdf);

    stats.totalWrittenBytes
        .name(name() + ".totalWrittenBytes")
        .desc("Number of bytes written")
        .flags(stats.disableBandwidthHists ? nozero : pdf);

    stats.averageWriteBW = stats.totalWrittenBytes / simSeconds;

    stats.readLatencyHist
        .init(params()->latency_bins)
        .name(name() + ".readLatencyHist")
        .desc("Read request-response latency")
        .flags(stats.disableLatencyHists ? nozero : pdf);

    stats.writeLatencyHist
        .init(params()->latency_bins)
        .name(name() + ".writeLatencyHist")
        .desc("Write request-response latency")
        .flags(stats.disableLatencyHists ? nozero : pdf);

    stats.ittReadRead
        .init(1, params()->itt_max_bin, params()->itt_max_bin /
              params()->itt_bins)
        .name(name() + ".ittReadRead")
        .desc("Read-to-read inter transaction time")
        .flags(stats.disableITTDists ? nozero : pdf);

    stats.ittWriteWrite
        .init(1, params()->itt_max_bin, params()->itt_max_bin /
              params()->itt_bins)
        .name(name() + ".ittWriteWrite")
        .desc("Write-to-write inter transaction time")
        .flags(stats.disableITTDists ? nozero : pdf);

    stats.ittReqReq
        .init(1, params()->itt_max_bin, params()->itt_max_bin /
              params()->itt_bins)
        .name(name() + ".ittReqReq")
        .desc("Request-to-request inter transaction time")
        .flags(stats.disableITTDists ? nozero : pdf);

    stats.outstandingReadsHist
        .init(params()->outstanding_bins)
        .name(name() + ".outstandingReadsHist")
        .desc("Outstanding read transactions")
        .flags(stats.disableOutstandingHists ? nozero : pdf);

    stats.outstandingWritesHist
        .init(params()->outstanding_bins)
        .name(name() + ".outstandingWritesHist")
        .desc("Outstanding write transactions")
        .flags(stats.disableOutstandingHists ? nozero : pdf);

    stats.readTransHist
        .init(params()->transaction_bins)
        .name(name() + ".readTransHist")
        .desc("Histogram of read transactions per sample period")
        .flags(stats.disableTransactionHists ? nozero : pdf);

    stats.writeTransHist
        .init(params()->transaction_bins)
        .name(name() + ".writeTransHist")
        .desc("Histogram of read transactions per sample period")
        .flags(stats.disableTransactionHists ? nozero : pdf);

    stats.readAddrDist
        .init(0)
        .name(name() + ".readAddrDist")
        .desc("Read address distribution")
        .flags(stats.disableAddrDists ? nozero : pdf);

    stats.writeAddrDist
        .init(0)
        .name(name() + ".writeAddrDist")
        .desc("Write address distribution")
        .flags(stats.disableAddrDists ? nozero : pdf);
}

void
CommMonitor::samplePeriodic()
{
    // the periodic stats update runs on the granularity of sample
    // periods, but in combination with this there may also be a
    // external resets and dumps of the stats (through schedStatEvent)
    // causing the stats themselves to capture less than a sample
    // period

    // only capture if we have not reset the stats during the last
    // sample period
    if (simTicks.value() >= samplePeriodTicks) {
        if (!stats.disableTransactionHists) {
            stats.readTransHist.sample(stats.readTrans);
            stats.writeTransHist.sample(stats.writeTrans);
        }

        if (!stats.disableBandwidthHists) {
            stats.readBandwidthHist.sample(stats.readBytes / samplePeriod);
            stats.writeBandwidthHist.sample(stats.writtenBytes / samplePeriod);
        }

        if (!stats.disableOutstandingHists) {
            stats.outstandingReadsHist.sample(stats.outstandingReadReqs);
            stats.outstandingWritesHist.sample(stats.outstandingWriteReqs);
        }
    }

    // reset the sampled values
    stats.readTrans = 0;
    stats.writeTrans = 0;

    stats.readBytes = 0;
    stats.writtenBytes = 0;

    schedule(samplePeriodicEvent, curTick() + samplePeriodTicks);
}

void
CommMonitor::startup()
{
    schedule(samplePeriodicEvent, curTick() + samplePeriodTicks);
}
