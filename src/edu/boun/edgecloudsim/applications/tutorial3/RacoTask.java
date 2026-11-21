// deadline = p.getStartTime() + duration. If a task arrives at 20 seconds and has a six-second allowance, its absolute deadline is 26 seconds. At time 22, it has four seconds left.
package edu.boun.edgecloudsim.applications.tutorial3;

import org.cloudbus.cloudsim.UtilizationModelFull;
import edu.boun.edgecloudsim.core.SimSettings;
import edu.boun.edgecloudsim.edge_client.CpuUtilizationModel_Custom;
import edu.boun.edgecloudsim.edge_client.Task;
import edu.boun.edgecloudsim.utils.TaskProperty;

final class RacoTask extends Task {
    final double deadline;
    final int ramMb;

    RacoServer server;
    double uploadSeconds;
    double uploadEnds;
    boolean uploaded;
    boolean correct = true;
    String refusal = "NO_FEASIBLE";

    RacoTask(TaskProperty p, int id, int brokerId, CpuUtilizationModel_Custom cpu) {
        super(p.getMobileDeviceId(), id,
              Math.max(1L, p.getLength()), p.getPesNumber(),
              Math.max(1L, p.getInputFileSize()),
              Math.max(1L, p.getOutputFileSize()),
              cpu, new UtilizationModelFull(), new UtilizationModelFull());

        int app = p.getTaskType();
        setTaskType(app);
        setUserId(brokerId);
        cpu.setTask(this);

        double duration = SimSettings.getInstance().getTaskLookUpTable()[app][13];
        if (duration <= 0 || p.getPesNumber() != 1) {
            throw new IllegalArgumentException("Each app needs a positive deadline and one core");
        }

        deadline = p.getStartTime() + duration;
        ramMb = RacoRules.TASK_RAM_MB[app];
    }
}