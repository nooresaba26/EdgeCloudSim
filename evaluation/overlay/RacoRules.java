// This is where I’ll change parameters during debugging. For example, changing FEEDBACK from 3.0 to 0.0 lets you test whether delayed feedback actually affects admission.
// ONLINE represents server availability. supports() represents application compatibility. TASK_RAM_MB supplies \(m_j\). The numerical values are experiment choices you can change.
package edu.boun.edgecloudsim.applications.tutorial3;

final class RacoRules {
    static final int B_MIN = 1;
    static final int B_MAX = Integer.parseInt(System.getProperty("raco.bMax", "5"));
    static final int STATIC_CAP = Integer.parseInt(System.getProperty("raco.staticCap", "3"));
    enum Policy { RANDOM, SHORTEST, REP_ONLY, ADMISSION_ONLY, STATIC, FULL }
    enum Fault {
        NORMAL(0, 0), MILD(0.05, 0.30), SEVERE(0.15, 0.70);
        final double withheld, badTotal;
        Fault(double withheld, double badTotal) {
            this.withheld = withheld;
            this.badTotal = badTotal;
        }
    }
    static final Policy POLICY = Policy.valueOf(System.getProperty("raco.policy", "FULL"));
    static final Fault FAULT = Fault.valueOf(System.getProperty("raco.fault", "SEVERE"));
    static final String TRACE = System.getProperty("raco.tasks");

    static final double KAPPA = Double.parseDouble(System.getProperty("raco.kappa", "0.025"));    // decay rate per simulated second
    static final double VERIFY = 0.15;    // seconds spent checking a result
    static final double FEEDBACK = Double.parseDouble(System.getProperty("raco.feedback", "3"));   // seconds for verdict to reach scheduler
    static final double LAST_ARRIVAL = 140.0;

    // Application order matches applications.xml: AR, health, infotainment.
    static final int[] TASK_RAM_MB = {128, 64, 96};
    static final boolean[] ONLINE = {true, true, true};

    static boolean supports(int host, int app) {
        // Servers 0 and 1 support every app. Server 2 supports the health app.
        return host != 2 || app == 1;
    }

    private RacoRules() {}
}