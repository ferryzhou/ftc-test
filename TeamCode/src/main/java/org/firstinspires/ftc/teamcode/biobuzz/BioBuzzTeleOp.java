package org.firstinspires.ftc.teamcode.biobuzz;

import com.qualcomm.robotcore.eventloop.opmode.OpMode;
import com.qualcomm.robotcore.eventloop.opmode.TeleOp;

/**
 * Driver-controlled op mode for the BIOBUZZ bot.
 *
 * Gamepad 1
 *   left stick        drive / strafe          right stick X   rotate
 *   left bumper hold  slow mode
 *   right trigger     intake in               left trigger    intake out
 *   right bumper hold spin up + feed (auto-selects hood and speed for the next element)
 *   A                 launcher off
 *   dpad up / down    nudge hood open / closed (tuning)
 *   Y                 clear the stored-element estimate
 *   back              set stored to 4 (after a manual reload)
 *
 * Before START: X = blue alliance, B = red alliance (needed to reject opponent NECTAR).
 */
@TeleOp(name = "BioBuzz TeleOp", group = "BioBuzz")
public class BioBuzzTeleOp extends OpMode {

    private BioBuzzRobot robot;
    private boolean dpadUpWas, dpadDownWas, yWas, backWas;

    @Override
    public void init() {
        robot = new BioBuzzRobot(hardwareMap);
        if (!robot.isHardwarePresent()) {
            telemetry.addData("MISSING", robot.getMissingDevice());
            telemetry.addData("Status", "check the robot configuration");
        } else {
            telemetry.addData("Status", "Initialized. X = blue, B = red");
        }
        telemetry.addData("Alliance", robot.getAlliance());
    }

    @Override
    public void init_loop() {
        if (gamepad1.x) robot.setAlliance(Alliance.BLUE);
        if (gamepad1.b) robot.setAlliance(Alliance.RED);
        telemetry.addData("Alliance", "%s  (X = blue, B = red)", robot.getAlliance());
        telemetry.addData("Sensor", robot.sense());
    }

    @Override
    public void loop() {
        if (!robot.isHardwarePresent()) {
            telemetry.addData("MISSING", robot.getMissingDevice());
            return;
        }

        // ---- drive ----
        double scale = gamepad1.left_bumper ? BioBuzzConfig.DRIVE_SLOW_SCALE : 1.0;
        robot.drive(-gamepad1.left_stick_y * scale, gamepad1.left_stick_x * scale,
                gamepad1.right_stick_x * scale);

        // ---- intake ----
        robot.requestIntake(gamepad1.right_trigger - gamepad1.left_trigger);

        // ---- launcher ----
        if (gamepad1.right_bumper) {
            robot.setLauncher(true);
        } else if (gamepad1.a) {
            robot.setLauncher(false);
        }
        robot.requestFeed(gamepad1.right_bumper);

        // ---- hood tuning and bookkeeping (edge-triggered) ----
        if (gamepad1.dpad_up && !dpadUpWas) robot.trimHood(+1);
        if (gamepad1.dpad_down && !dpadDownWas) robot.trimHood(-1);
        if (gamepad1.y && !yWas) robot.clearStored();
        if (gamepad1.back && !backWas) robot.setPreloaded(BioBuzzConfig.MAX_ELEMENTS);
        dpadUpWas = gamepad1.dpad_up;
        dpadDownWas = gamepad1.dpad_down;
        yWas = gamepad1.y;
        backWas = gamepad1.back;

        robot.update();
        robot.addTelemetry(telemetry);
    }

    @Override
    public void stop() {
        if (robot.isHardwarePresent()) {
            robot.stop();
        }
    }
}
