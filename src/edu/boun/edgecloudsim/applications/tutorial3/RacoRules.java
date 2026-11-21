// This is where I’ll change parameters during debugging. For example, changing FEEDBACK from 3.0 to 0.0 lets you test whether delayed feedback actually affects admission.
// ONLINE represents server availability. supports() represents application compatibility. TASK_RAM_MB supplies \(m_j\). The numerical values are experiment choices you can change.
package edu.boun.edgecloudsim.applications.tutorial3;

final class RacoRules {
    static final int B_MIN = 1;
    static final int B_MAX = 5;

    static final double KAPPA = 0.025;    // decay rate per simulated second
    static final double VERIFY = 0.15;    // seconds spent checking a result
    static final double FEEDBACK = 3.0;   // seconds for verdict to reach scheduler
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