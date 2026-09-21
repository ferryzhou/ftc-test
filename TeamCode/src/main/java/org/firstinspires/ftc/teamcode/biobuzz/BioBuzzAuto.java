package org.firstinspires.ftc.teamcode.biobuzz;

import com.qualcomm.robotcore.eventloop.opmode.Autonomous;
import com.qualcomm.robotcore.eventloop.opmode.LinearOpMode;
import com.qualcomm.robotcore.util.ElapsedTime;

/**
 * Simple time-based autonomous: launch the four pre-loaded POLLEN at the HIVE, then drive off
 * the wall for LEAVE points. Starting position: robot against the perimeter wall with the
 * launcher already aimed at the upward-facing CELL. Distances are time based, so tune the
 * two constants on the field.
 *
 * Alliance is chosen with X (blue) / B (red) during init and carried into TeleOp.
 */
@Autonomous(name = "BioBuzz Auto: launch 4 + leave", group = "BioBuzz")
public class BioBuzzAuto extends LinearOpMode {

    /** Seconds of feeding for four elements plus margin. */
    private static final double LAUNCH_SECONDS = 4 * BioBuzzConfig.FEED_SECONDS_PER_ELEMENT + 1.0;
    /** Seconds to wait for the wheel before giving up on spin-up. */
    private static final double SPINUP_TIMEOUT = 3.0;
    /** Drive time and power for LEAVE (moving off the wall). */
    private static final double LEAVE_SECONDS = 0.8;
    private static final double LEAVE_POWER = 0.4;

    @Override
    public void runOpMode() {
        BioBuzzRobot robot = new BioBuzzRobot(hardwareMap);
        if (!robot.isHardwarePresent()) {
            telemetry.addData("MISSING", robot.getMissingDevice());
            telemetry.update();
        }
        robot.setPreloaded(4);

        while (opModeInInit()) {
            if (gamepad1.x) robot.setAlliance(Alliance.BLUE);
            if (gamepad1.b) robot.setAlliance(Alliance.RED);
            telemetry.addData("Alliance", "%s  (X = blue, B = red)", robot.getAlliance());
            telemetry.addData("Status", robot.isHardwarePresent() ? "ready" : "MISSING " + robot.getMissingDevice());
            telemetry.update();
        }
        if (!opModeIsActive() || !robot.isHardwarePresent()) {
            return;
        }

        ElapsedTime timer = new ElapsedTime();

        // 1. spin up
        robot.setLauncher(true);
        timer.reset();
        while (opModeIsActive() && timer.seconds() < SPINUP_TIMEOUT && !robot.readyToFeed()) {
            robot.update();
            robot.addTelemetry(telemetry);
            telemetry.update();
        }

        // 2. feed all four
        timer.reset();
        while (opModeIsActive() && timer.seconds() < LAUNCH_SECONDS) {
            robot.requestFeed(true);
            robot.update();
            robot.addTelemetry(telemetry);
            telemetry.update();
        }
        robot.setLauncher(false);
        robot.requestFeed(false);
        robot.update();

        // 3. LEAVE: drive off the perimeter wall
        timer.reset();
        while (opModeIsActive() && timer.seconds() < LEAVE_SECONDS) {
            robot.drive(LEAVE_POWER, 0, 0);
            robot.update();
        }
        robot.stop();
    }
}
