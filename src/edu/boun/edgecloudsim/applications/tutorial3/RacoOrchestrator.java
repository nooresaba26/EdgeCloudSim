package edu.boun.edgecloudsim.applications.tutorial3;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import org.cloudbus.cloudsim.Vm;
import org.cloudbus.cloudsim.core.CloudSim;
import edu.boun.edgecloudsim.core.SimManager;
import edu.boun.edgecloudsim.core.SimSettings;
import edu.boun.edgecloudsim.edge_client.Task;
import edu.boun.edgecloudsim.edge_server.EdgeHost;
import edu.boun.edgecloudsim.edge_server.EdgeVM;
import edu.boun.edgecloudsim.network.NetworkModel;
import edu.boun.edgecloudsim.utils.SimUtils;

final class RacoOrchestrator extends SampleEdgeOrchestrator {
    private record Candidate(RacoServer server, double reputation) {}

    private final List<RacoServer> servers = new ArrayList<>();
    private final Random lottery = new Random(SimUtils.getSeed() ^ 713L);

    RacoOrchestrator() {
        super("THESIS", "THESIS");
    }

    @Override
    public int getDeviceToOffload(Task task) {
        return SimSettings.GENERIC_EDGE_DEVICE_ID;
    }

    private void discoverServers() {
        var manager = SimManager.getInstance().getEdgeServerManager();
        int count = SimSettings.getInstance().getNumOfEdgeHosts();

        if (count != RacoRules.ONLINE.length) {
            throw new IllegalStateException("Host count and ONLINE array differ");
        }

        for (int h = 0; h < count; h++) {
            List<EdgeVM> vms = manager.getVmList(h);
            if (vms.size() != 1 || vms.get(0).getNumberOfPes() != 1) {
                throw new IllegalStateException("Use one single-core VM per host");
            }
            servers.add(new RacoServer(vms.get(0)));
        }
    }

    @Override
    public Vm getVmToOffload(Task raw, int tier) {
        if (servers.isEmpty()) discoverServers();

        RacoTask task = (RacoTask) raw;
        double now = CloudSim.clock();
        NetworkModel net = SimManager.getInstance().getNetworkModel();

        // All three hosts are on the same WLAN in this first experiment.
        double up = net.getUploadDelay(task.getMobileDeviceId(), tier, task);
        double down = net.getDownloadDelay(tier, task.getMobileDeviceId(), task);
        if (up <= 0 || down <= 0) return null;

        List<Candidate> eligible = new ArrayList<>();
        int physicallyFeasible = 0;
        double totalWeight = 0;

        for (RacoServer server : servers) {
            EdgeHost host = (EdgeHost) server.vm.getHost();

            // 1. Availability, application support, memory, and connectivity.
            if (!RacoRules.ONLINE[server.id]) continue;
            if (!RacoRules.supports(server.id, task.getTaskType())) continue;
            if (server.freeRam() < task.ramMb) continue;
            if (host.getLocation().getServingWlanId()
                    != task.getSubmittedLocation().getServingWlanId()) continue;

            // 2. Predicted upload + queue + execution + download + verification.
            double wait = Math.max(0, server.cpuFreeAt(now) - (now + up));
            double predicted = up + wait + server.executionTime(task)
                    + down + RacoRules.VERIFY;
            if (predicted > task.deadline - now) continue;
            physicallyFeasible++;

            // 3. Admission condition U_i + 1 <= B_i.
            double r = server.reputation(now);
            if (server.unresolved() + 1 > server.cap(r)) continue;

            eligible.add(new Candidate(server, r));
            totalWeight += r;
        }

        if (eligible.isEmpty()) {
            task.refusal = physicallyFeasible == 0 ? "NO_FEASIBLE" : "CAP_FULL";
            return null;
        }

        // 4. Draw one server with probability R_i / sum(R).
        double ticket = lottery.nextDouble() * totalWeight;
        Candidate winner = eligible.get(eligible.size() - 1);
        for (Candidate c : eligible) {
            ticket -= c.reputation();
            if (ticket < 0) {
                winner = c;
                break;
            }
        }

        task.server = winner.server();
        task.uploadSeconds = up;
        return task.server.vm;
    }
}