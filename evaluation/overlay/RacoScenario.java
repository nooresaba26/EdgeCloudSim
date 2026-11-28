package edu.boun.edgecloudsim.applications.tutorial3;

import java.util.Calendar;
import org.cloudbus.cloudsim.Log;
import org.cloudbus.cloudsim.core.CloudSim;
import edu.boun.edgecloudsim.core.SimManager;
import edu.boun.edgecloudsim.core.SimSettings;
import edu.boun.edgecloudsim.edge_client.MobileDeviceManager;
import edu.boun.edgecloudsim.edge_orchestrator.EdgeOrchestrator;
import edu.boun.edgecloudsim.mobility.MobilityModel;
import edu.boun.edgecloudsim.network.NetworkModel;
import edu.boun.edgecloudsim.task_generator.IdleActiveLoadGenerator;
import edu.boun.edgecloudsim.task_generator.LoadGeneratorModel;
import edu.boun.edgecloudsim.utils.Location;
import edu.boun.edgecloudsim.utils.SimLogger;

public final class RacoScenario extends SampleScenarioFactory {
    private final int deviceCount;
    private final double seconds;

    private RacoScenario(int devices, double seconds) {
        super(devices, seconds, "THESIS", "THESIS");
        this.deviceCount = devices;
        this.seconds = seconds;
    }

    @Override public EdgeOrchestrator getEdgeOrchestrator() {
        return new RacoOrchestrator();
    }

    @Override public MobileDeviceManager getMobileDeviceManager() throws Exception {
        return new RacoBroker();
    }

    @Override public MobilityModel getMobilityModel() {
        return new MobilityModel(deviceCount, seconds) {
            private final Location campus = new Location(0, 0, 0, 0);
            @Override public void initialize() {}
            @Override public Location getLocation(int device, double time) {
                return campus;
            }
        };
    }

    @Override public NetworkModel getNetworkModel() {
        return new SampleNetworkModel(deviceCount, "THESIS") {
            // Count downloads in the same shared WLAN contention counter as uploads.
            @Override public void downloadStarted(Location location, int device) {
                super.uploadStarted(location, SimSettings.GENERIC_EDGE_DEVICE_ID);
            }
            @Override public void downloadFinished(Location location, int device) {
                super.uploadFinished(location, SimSettings.GENERIC_EDGE_DEVICE_ID);
            }
        };
    }

    @Override public LoadGeneratorModel getLoadGeneratorModel() {
        return new IdleActiveLoadGenerator(deviceCount, RacoRules.LAST_ARRIVAL, "THESIS") {
            @Override public void initializeModel() {
                super.initializeModel();
                getTaskList().removeIf(t -> t.getStartTime() > RacoRules.LAST_ARRIVAL);
            }
        };
    }

    public static void main(String[] args) throws Exception {
        String cfg = "scripts/thesis_manual/config/";
        SimSettings settings = SimSettings.getInstance();

        if (!settings.initialize(cfg + "default_config.properties",
                cfg + "edge_devices.xml", cfg + "applications.xml")) {
            throw new IllegalArgumentException("Cannot initialize Raco configuration");
        }

        for (double[] app : settings.getTaskLookUpTable()) {
            if (app[13] <= 0 || RacoRules.LAST_ARRIVAL + app[13]
                    + RacoRules.FEEDBACK + 0.000001 >= settings.getSimulationTime()) {
                throw new IllegalArgumentException("Check app deadlines and simulation end time");
            }
        }

        Log.disable();
        SimLogger.getInstance().simStarted("sim_results", "THESIS");
        CloudSim.init(2, Calendar.getInstance(), false, 0.01);

        int devices = Integer.parseInt(System.getProperty("raco.devices",
                String.valueOf(settings.getMinNumOfMobileDev())));
        if (devices < 1 || !Double.isFinite(RacoRules.KAPPA) || RacoRules.KAPPA < 0
                || !Double.isFinite(RacoRules.FEEDBACK) || RacoRules.FEEDBACK < 0
                || RacoRules.STATIC_CAP < 1 || RacoRules.B_MAX < RacoRules.B_MIN) {
            throw new IllegalArgumentException("Invalid evaluation parameter");
        }
        RacoScenario factory = new RacoScenario(devices, settings.getSimulationTime());
        SimManager manager = new SimManager(factory, devices, "THESIS", "THESIS");
        manager.startSimulation();
        ((RacoBroker) manager.getMobileDeviceManager()).printSummary();
    }
}