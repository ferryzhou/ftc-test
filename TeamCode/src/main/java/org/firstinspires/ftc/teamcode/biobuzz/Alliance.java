package org.firstinspires.ftc.teamcode.biobuzz;

/**
 * Alliance colour. Kept in a static field so the choice made before AUTO carries over to TELEOP
 * (the Robot Controller keeps static state between op modes).
 */
public enum Alliance {
    RED, BLUE;

    private static Alliance selected = RED;

    public static Alliance get() {
        return selected;
    }

    public static void set(Alliance alliance) {
        selected = alliance;
    }
}
