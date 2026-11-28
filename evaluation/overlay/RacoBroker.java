package edu.boun.edgecloudsim.applications.tutorial3;

import java.util.Locale;
import java.util.SplittableRandom;
import org.cloudbus.cloudsim.Cloudlet;
import org.cloudbus.cloudsim.Vm;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.core.CloudSimTags;
import org.cloudbus.cloudsim.core.SimEvent;
import edu.boun.edgecloudsim.core.SimManager;
import edu.boun.edgecloudsim.core.SimSettings;
import edu.boun.edgecloudsim.edge_client.CpuUtilizationModel_Custom;
import edu.boun.edgecloudsim.edge_client.MobileDeviceManager;
import edu.boun.edgecloudsim.network.NetworkModel;
import edu.boun.edgecloudsim.utils.SimUtils;
import edu.boun.edgecloudsim.utils.TaskProperty;

final class RacoBroker extends MobileDeviceManager {
    private static final int UPLOADED = 110001;
    private static final int DOWNLOADED = 110002;
    private static final int VERIFIED = 110003;
    private static final int REPORT = 110004;
    private static final int TIMEOUT = 110005;
    private static final int EDGE = SimSettings.GENERIC_EDGE_DEVICE_ID;

    private record Verdict(RacoTask task, boolean ok, String cause, double occurred) {}

    private final java.util.List<RacoTask> trace = new java.util.ArrayList<>();
    private int offered, assigned, accepted, failed, capFull, noFeasible;

    RacoBroker() throws Exception { super(); }

    @Override public void initialize() {}

    @Override public CpuUtilizationModel_Custom getCpuUtilizationModel() {
        return new CpuUtilizationModel_Custom();
    }

    @Override protected void submitCloudlets() {
        // startCpu() submits each task when its upload and queue wait are over.
    }

    @Override public void submitTask(TaskProperty input) {
        double now = CloudSim.clock();
        var sim = SimManager.getInstance();
        RacoTask task = new RacoTask(input, ++offered, getId(), getCpuUtilizationModel());
        if (RacoRules.TRACE != null) trace.add(task);
        task.setSubmittedLocation(sim.getMobilityModel()
                .getLocation(task.getMobileDeviceId(), now));

        var orchestrator = sim.getEdgeOrchestrator();
        int tier = orchestrator.getDeviceToOffload(task);
        Vm vm = orchestrator.getVmToOffload(task, tier);

        if (vm == null) {
            task.terminal = task.refusal;
            if (task.refusal.equals("CAP_FULL")) capFull++;
            else noFeasible++;
            if (RacoRules.TRACE == null) System.out.printf(Locale.ROOT, "%.4f task=%d %s%n",
                    now, task.getCloudletId(), task.refusal);
            return;
        }

        assigned++;
        task.assignedAt = now;
        task.setAssociatedDatacenterId(tier);
        task.setAssociatedHostId(task.server.id);
        task.setAssociatedVmId(vm.getId());
        task.setVmId(vm.getId());

        task.server.assign(task, now);
        log(task, "ASSIGNED", now);
        sim.getNetworkModel().uploadStarted(task.getSubmittedLocation(), EDGE);
        schedule(getId(), task.uploadSeconds, UPLOADED, task);
        schedule(getId(), task.deadline - now + RacoRules.FEEDBACK + 0.000001,
                TIMEOUT, task);
    }

    private void startCpu(RacoServer server) {
        RacoTask task = server.startIfReady(CloudSim.clock());
        if (task == null) return;

        log(task, "CPU_START", CloudSim.clock());
        int datacenter = getVmsToDatacentersMap().get(task.getVmId());
        schedule(datacenter, 0, CloudSimTags.CLOUDLET_SUBMIT, task);
    }

    @Override protected void processCloudletReturn(SimEvent event) {
        RacoTask task = (RacoTask) event.getData();
        double now = CloudSim.clock();

        task.cpuEnd = now;
        task.server.cpuFinished(task);
        log(task, "CPU_DONE", now);
        startCpu(task.server);

        if (task.getStatus() != Cloudlet.SUCCESS) {
            reportLater(task, false, "EXEC_FAILURE");
            return;
        }

        // Synthetic service change so that you can exercise failure and timeout.
        // Only the service side sees this draw. The orchestrator sees later feedback.
        if (task.server.id == 1 && now >= 75.0) {
            long key = SimUtils.getSeed() ^ ((long) task.getCloudletId() << 32)
                    ^ task.server.id;
            double draw = new SplittableRandom(key).nextDouble();
            if (draw < RacoRules.FAULT.withheld) {
                task.withheld = true;
                log(task, "RESULT_WITHHELD", now);
                return;
            }
            task.correct = draw >= RacoRules.FAULT.badTotal;
        }

        NetworkModel net = SimManager.getInstance().getNetworkModel();
        double down = net.getDownloadDelay(EDGE, task.getMobileDeviceId(), task);
        if (down <= 0) {
            reportLater(task, false, "BANDWIDTH");
            return;
        }

        net.downloadStarted(task.getSubmittedLocation(), EDGE);
        schedule(getId(), down, DOWNLOADED, task);
    }

    private void reportLater(RacoTask task, boolean ok, String cause) {
        Verdict v = new Verdict(task, ok, cause, CloudSim.clock());
        schedule(getId(), RacoRules.FEEDBACK, REPORT, v);
    }

    @Override protected void processOtherEvent(SimEvent event) {
        double now = CloudSim.clock();
        NetworkModel net = SimManager.getInstance().getNetworkModel();

        switch (event.getTag()) {
            case UPLOADED -> {
                RacoTask t = (RacoTask) event.getData();
                net.uploadFinished(t.getSubmittedLocation(), EDGE);
                t.uploaded = true;
                startCpu(t.server);
            }
            case DOWNLOADED -> {
                RacoTask t = (RacoTask) event.getData();
                net.downloadFinished(t.getSubmittedLocation(), EDGE);
                schedule(getId(), RacoRules.VERIFY, VERIFIED, t);
            }
            case VERIFIED -> {
                RacoTask t = (RacoTask) event.getData();
                t.verified = now;
                String cause = t.correct ? "OK" : "INVALID";
                log(t, "VERIFIED_" + cause, now);
                reportLater(t, t.correct, cause);
            }
            case REPORT -> {
                Verdict v = (Verdict) event.getData();
                if (v.occurred() <= v.task().deadline) {
                    resolve(v.task(), v.ok(), v.cause(), v.occurred());
                } else {
                    log(v.task(), "LATE_REPORT", v.occurred());
                }
            }
            case TIMEOUT -> {
                RacoTask t = (RacoTask) event.getData();
                resolve(t, false, "TIMEOUT", t.deadline);
            }
            default -> super.processOtherEvent(event);
        }
    }

    private void resolve(RacoTask task, boolean ok, String cause, double occurred) {
        if (!task.server.observe(task, ok, occurred, CloudSim.clock())) return;
        task.terminal = cause;
        task.terminalAt = occurred;
        task.observed = CloudSim.clock();
        if (ok) accepted++;
        else failed++;
        log(task, "RESOLVED_" + cause, occurred);
    }

    private void log(RacoTask task, String event, double occurred) {
        double now = CloudSim.clock();
        double r = task.server.reputation(now);
        if (RacoRules.TRACE != null) return;
        System.out.printf(Locale.ROOT,
                "%.4f task=%d host=%d %s occurred=%.4f deadline=%.4f U=%d R=%.4f B=%d%n",
                now, task.getCloudletId(), task.server.id, event, occurred,
                task.deadline, task.server.unresolved(), r, task.server.cap(r));
    }

    void printSummary() throws java.io.IOException {
        if (RacoRules.TRACE != null) {
            RacoTrace.write(java.nio.file.Path.of(RacoRules.TRACE), trace);
            if (offered != assigned + capFull + noFeasible || assigned != accepted + failed) {
                throw new IllegalStateException("Inconsistent task accounting");
            }
        }
        System.out.printf("Offered=%d Assigned=%d Accepted=%d Failed=%d "
                        + "NoFeasible=%d CapFull=%d Pending=%d%n",
                offered, assigned, accepted, failed, noFeasible, capFull,
                assigned - accepted - failed);
    }
}
// CPU_DONE releases RAM and the processor. VERIFIED_OK says the device has a usable result. 
// RESOLVED_OK says the scheduler has learned that fact and released one pending slot.
//  The first timestamp on each log line is when the event is processed.
//  occurred records the time used to age the evidence.

// The server change at 75 seconds is a synthetic test condition. 
// It lets you see invalid results and silent timeouts in the log.
//  A failed task measures an unsuccessful service outcome. 
// It does not establish malicious intent.