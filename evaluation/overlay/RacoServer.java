package edu.boun.edgecloudsim.applications.tutorial3;

import java.util.ArrayDeque;
import java.util.HashSet;
import java.util.Set;
import edu.boun.edgecloudsim.edge_server.EdgeVM;

final class RacoServer {
    final EdgeVM vm;
    final int id;

    private final ArrayDeque<RacoTask> queue = new ArrayDeque<>();
    private final Set<Integer> pending = new HashSet<>();

    private RacoTask running;
    private double expectedCpuEnd;
    private int reservedRam;

    private double successes;
    private double failures;
    private double lastUpdate;

    RacoServer(EdgeVM vm) {
        this.vm = vm;
        this.id = vm.getHost().getId();
    }

    int freeRam() {
        return vm.getRam() - reservedRam;
    }

    double executionTime(RacoTask task) {
        return task.getCloudletLength() / vm.getMips();
    }

    // Estimated finish time of all CPU work already booked on this server.
    double cpuFreeAt(double now) {
        double free = running == null ? now : Math.max(now, expectedCpuEnd);
        for (RacoTask task : queue) {
            free = Math.max(free, task.uploadEnds) + executionTime(task);
        }
        return free;
    }

    private void decayTo(double now) {
        double factor = Math.exp(-RacoRules.KAPPA * (now - lastUpdate));
        successes *= factor;
        failures *= factor;
        lastUpdate = now;
    }

    double reputation(double now) {
        decayTo(now);
        return (1.0 + successes) / (2.0 + successes + failures);
    }

    int cap(double reputation) {
        switch (RacoRules.POLICY) {
            case RANDOM, SHORTEST, REP_ONLY: return Integer.MAX_VALUE;
            case STATIC: return RacoRules.STATIC_CAP;
            default: break;
        }
        return RacoRules.B_MIN + (int) Math.floor(
                (RacoRules.B_MAX - RacoRules.B_MIN) * reputation);
    }

    int unresolved() {
        return pending.size();
    }

    void assign(RacoTask task, double now) {
        if (!pending.add(task.getCloudletId())) {
            throw new IllegalStateException("Duplicate assignment");
        }
        reservedRam += task.ramMb;
        task.uploadEnds = now + task.uploadSeconds;
        queue.addLast(task);
    }

    RacoTask startIfReady(double now) {
        RacoTask first = queue.peekFirst();
        if (running != null || first == null || !first.uploaded) return null;

        running = queue.removeFirst();
        expectedCpuEnd = now + executionTime(running);
        return running;
    }

    void cpuFinished(RacoTask task) {
        if (running != task) throw new IllegalStateException("Unexpected CPU return");
        running = null;
        reservedRam -= task.ramMb;
    }

    boolean observe(RacoTask task, boolean accepted, double occurred, double now) {
        if (!pending.remove(task.getCloudletId())) return false;

        decayTo(now);
        double weight = Math.exp(-RacoRules.KAPPA * (now - occurred));
        if (accepted) successes += weight;
        else failures += weight;
        return true;
    }
}
//  This file keeps two kinds of state for each server:
// - Physical state tells you when the CPU will be free and how much task RAM is available.
// - Outcome state tells you how many assignments remain unresolved and how trustworthy the observed service history is.
// How this implements the equations:
// - reputation() computes \(R_i=(1+S_i)/(2+S_i+F_i)\). A new server starts at \(0.5\).
// - decayTo() ages past evidence. observe() also ages a newly received report from when the outcome happened to when the scheduler learned it.
// - pending.size() is \(U_i\). assign() increases it. Only observe() can decrease it.
// - pending.remove(...) returns false if a timeout already resolved that task. A late result therefore cannot free a second slot.
// - The CPU queue follows assignment order. startIfReady() enforces that ordering in the actual simulation, so the queue-time estimate corresponds to a real scheduling rule.