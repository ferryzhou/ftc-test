package org.firstinspires.ftc.teamcode.biobuzz;

/**
 * Every hardware-configuration name and tunable number for the BIOBUZZ bot in one place.
 *
 * The device names match goBILDA's StarterBot samples so a Control Hub configured for the
 * stock 3200-2627-0004 keeps working; the two new devices (hood servo, element sensor) are
 * the only additions.  All the numbers are starting points to tune on the real robot.
 */
public final class BioBuzzConfig {
    private BioBuzzConfig() {}

    // ---- drive (mecanum, one 19.2:1 Yellow Jacket per corner through miter gears) ----
    public static final String FRONT_LEFT = "Front_Left";
    public static final String FRONT_RIGHT = "Front_Right";
    public static final String REAR_LEFT = "Rear_Left";
    public static final String REAR_RIGHT = "Rear_Right";

    // ---- intake ----
    /** 50.9:1 Yellow Jacket driving the 48 mm Gecko wheel conveyor through the 100T:20T gears. */
    public static final String INTAKE = "intake";
    /** 2000-0025-0003 speed servos (continuous) on the 72 mm corner Gecko wheels. */
    public static final String LEFT_INTAKE_SERVO = "left_intake_servo";
    public static final String RIGHT_INTAKE_SERVO = "right_intake_servo";

    // ---- launcher ----
    /** 1:1 converted Yellow Jacket spinning the 96 mm Hogback wheel. */
    public static final String LAUNCHER = "launcher";
    /** 2000-0025-0002 torque servo (continuous) turning the four-paddle windmill feeder. */
    public static final String WINDMILL = "windmill";
    /** NEW: 2000-0025-0002 torque servo (positional) that sets the hood gap. */
    public static final String HOOD = "hood";
    /** NEW: REV Color Sensor V3 in the chute wall, classifies POLLEN / NECTAR and rejects opponent NECTAR. */
    public static final String ELEMENT_SENSOR = "element_sensor";

    // ---- launcher velocities, encoder ticks per second (28 ticks/rev at the bare motor) ----
    // 1250 t/s = 2678 rpm = 13.5 m/s Hogback surface speed. goBILDA's stock POLLEN values.
    public static final int LAUNCH_VELOCITY_POLLEN = 1250;
    public static final int LAUNCH_MIN_VELOCITY_POLLEN = 1200;
    // NECTAR has the same ballistic coefficient as POLLEN (see doc/biobuzz-bot/README.md), so the
    // same exit speed lands it on the same spot. Keep the two targets equal: the shot simulation
    // showed a 4% higher NECTAR target moves its landing point 0.4 m further out. The heavier
    // ball's larger droop is handled by waiting for the wheel to recover before the next feed.
    public static final int LAUNCH_VELOCITY_NECTAR = 1250;
    public static final int LAUNCH_MIN_VELOCITY_NECTAR = 1200;
    // PIDF for RUN_USING_ENCODER on the 1:1 launcher motor (goBILDA's tuned values).
    public static final double LAUNCH_P = 40, LAUNCH_I = 0, LAUNCH_D = 0, LAUNCH_F = 12.5;

    // ---- hood servo positions (0..1). POLLEN = stock 47 mm gap, NECTAR = about 68 mm gap ----
    public static final double HOOD_POLLEN = 0.30;
    public static final double HOOD_NECTAR = 0.55;
    public static final double HOOD_STEP = 0.02;       // dpad nudge per press
    public static final double HOOD_SETTLE_SECONDS = 0.35;

    // ---- feeding ----
    public static final double WINDMILL_FEED_POWER = 1.0;
    /** Approximate time the windmill needs to feed one element (one quarter turn). */
    public static final double FEED_SECONDS_PER_ELEMENT = 0.5;
    /** Extra intake power applied while launching to keep the hopper moving (goBILDA trick). */
    public static final double INTAKE_ASSIST_WHILE_LAUNCHING = 0.5;

    // ---- element sensor ----
    public static final float SENSOR_GAIN = 8f;
    /** Element is "present" when closer than this (mm) to the colour sensor. */
    public static final double SENSOR_PRESENT_MM = 45;
    /** HSV hue bands, degrees. POLLEN is yellow; NECTAR is red or blue. */
    public static final float HUE_YELLOW_MIN = 35, HUE_YELLOW_MAX = 80;
    public static final float HUE_BLUE_MIN = 190, HUE_BLUE_MAX = 260;
    public static final float HUE_RED_MAX = 20, HUE_RED_MIN = 335;   // wraps around 0
    /** How long the intake runs backwards after an opponent NECTAR is seen (G408). */
    public static final double REJECT_SECONDS = 0.7;

    // ---- game limits ----
    /** G407: never CONTROL more than four scoring elements. The intake stops at this count. */
    public static final int MAX_ELEMENTS = 4;

    // ---- drive feel ----
    public static final double DRIVE_SLOW_SCALE = 0.4;
}
