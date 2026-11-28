package edu.boun.edgecloudsim.applications.tutorial3;

import java.nio.file.Files;
import java.nio.file.Path;
import java.io.IOException;
import java.util.List;

/** One record for every offered task. Empty fields describe unobserved events. */
final class RacoTrace {
    private RacoTrace() {}
    static void write(Path path, List<RacoTask> tasks) throws IOException {
        try (var out = Files.newBufferedWriter(path)) {
            out.write("task,device,app,arrival_s,input_kb,output_kb,work_mi,cores,ram_mb,deadline_s,"
                    + "host,assigned_s,predicted_s,r_before,u_before,cap_before,h1_feasible,h1_admissible,"
                    + "cpu_done_s,withheld,verified_s,verified_correct,terminal,terminal_s,observed_s");
            out.newLine();
            for (var t : tasks) {
                var p = t.input;
                if (t.terminal == null) throw new IllegalStateException("Unresolved task");
                String cap = t.capBefore < 0 || t.capBefore == Integer.MAX_VALUE ? "" : Integer.toString(t.capBefore);
                out.write(String.join(",",
                        Integer.toString(t.getCloudletId()), Integer.toString(p.getMobileDeviceId()),
                        Integer.toString(p.getTaskType()), number(p.getStartTime()), Long.toString(p.getInputFileSize()),
                        Long.toString(p.getOutputFileSize()), Long.toString(p.getLength()), Integer.toString(p.getPesNumber()),
                        Integer.toString(t.ramMb), number(t.deadline), t.server == null ? "" : Integer.toString(t.server.id),
                        number(t.assignedAt), number(t.predicted), number(t.reputationBefore),
                        t.unresolvedBefore < 0 ? "" : Integer.toString(t.unresolvedBefore), cap,
                        t.h1Feasible ? "1" : "0", t.h1Admissible ? "1" : "0", number(t.cpuEnd),
                        t.withheld ? "1" : "0", number(t.verified),
                        Double.isNaN(t.verified) ? "" : (t.correct ? "1" : "0"),
                        t.terminal, number(t.terminalAt), number(t.observed)));
                out.newLine();
            }
        }
    }
    private static String number(double value) { return Double.isNaN(value) ? "" : Double.toString(value); }
}
